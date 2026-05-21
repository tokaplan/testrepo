/**
 * LangChainNodeJs - multi-agent (agent-as-tool + sequential workflow) port
 * of WeatherChatMAF.
 *
 * Topology per protocol:
 *
 *   StateGraph (sequential workflow)
 *   +- MainAgent (createReactAgent, tools=[weatherDataAgentTool])
 *   |  +- weatherDataAgentTool   <-- tool() wrapping inner data agent (agent-as-tool)
 *   |     +- DataAgent (createReactAgent, tools=[getCurrentWeather])
 *   +- VerifierAgent (createReactAgent, no tools)
 */

import { AzureChatOpenAI, ChatOpenAI } from "@langchain/openai";
import { tool } from "@langchain/core/tools";
import {
  AIMessage,
  HumanMessage,
  SystemMessage,
} from "@langchain/core/messages";
import { createReactAgent } from "@langchain/langgraph/prebuilt";
import {
  StateGraph,
  START,
  END,
  MessagesAnnotation,
} from "@langchain/langgraph";
import { z } from "zod";

import { randomUUID } from "node:crypto";
import process from "node:process";

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------
const ENDPOINT =
  "https://alkap-mc9jji6o-eastus2.services.ai.azure.com/api/projects/alkap-mc9jji6o-eastus2_project";
const BASE_URL = ENDPOINT + "/openai/v1/";
const AZURE_OPENAI_ENDPOINT =
  "https://alkap-mc9jji6o-eastus2.cognitiveservices.azure.com";
const AZURE_OPENAI_API_VERSION = "2025-04-01-preview";

const DEPLOYMENT = "deployment-gpt-5.4-mini";

const SERVICE_NAME = "LangChainNodeJs";
const USER_PROMPT = "What's the weather like in Seattle and San Francisco?";

const DATA_INSTRUCTIONS =
  "You are a weather data agent. You look up weather information for one or " +
  "more cities using the get_current_weather tool. Call the tool ONCE per " +
  "requested city, then return a concise JSON-like string containing all " +
  "results. Do not add any commentary.";

const MAIN_INSTRUCTIONS =
  "You are a friendly weather assistant. When the user asks about weather, " +
  "delegate the lookup to the weather_data_agent tool by passing it the list " +
  "of cities (e.g. 'Seattle, WA; San Francisco, CA'). Then summarize the " +
  "results to the user in plain English.";

const VERIFIER_INSTRUCTIONS =
  "You are a verifier agent. You will see a conversation between a user and " +
  "a weather assistant. Sanity-check the assistant's response. Look for: " +
  "(1) hallucinated cities not in the user's question, " +
  "(2) impossible temperature/condition pairs, " +
  "(3) missing cities the user asked about. " +
  "Reply with one line starting with 'VERIFIED: ...' if the response is sound, " +
  "or 'WARN: ...' if not. Do not call any tools.";

// ---------------------------------------------------------------------------
// Inner weather tool (raw function)
// ---------------------------------------------------------------------------
const WEATHER_DATA = {
  "seattle, wa": [55, "Rainy"],
  "san francisco, ca": [63, "Foggy"],
  "new york, ny": [72, "Sunny"],
};

const getCurrentWeather = tool(
  async ({ location, unit }) => {
    const [tempF, condition] = WEATHER_DATA[location.toLowerCase()] ?? [
      68,
      "Partly cloudy",
    ];
    const u = unit ?? "fahrenheit";
    const temp = u === "celsius" ? Math.trunc(((tempF - 32) * 5) / 9) : tempF;
    const unitLabel = u === "celsius" ? "C" : "F";
    console.log(`[Tool] get_current_weather("${location}", "${u}")`);
    return JSON.stringify({
      location,
      temperature: `${temp}${unitLabel}`,
      condition,
    });
  },
  {
    name: "get_current_weather",
    description: "Gets the current weather for a given location.",
    schema: z.object({
      location: z
        .string()
        .describe("The city and state, e.g. San Francisco, CA"),
      unit: z
        .enum(["fahrenheight", "fahrenheit", "celsius"])
        .optional()
        .describe("The temperature unit (defaults to fahrenheit)"),
    }),
  }
);

// ---------------------------------------------------------------------------
// Chat client factories
// ---------------------------------------------------------------------------
function makeAzureChat(deployment, apiKey) {
  return new AzureChatOpenAI({
    azureOpenAIApiKey: apiKey,
    azureOpenAIApiInstanceName: "alkap-mc9jji6o-eastus2",
    azureOpenAIApiDeploymentName: deployment,
    azureOpenAIApiVersion: AZURE_OPENAI_API_VERSION,
    azureOpenAIBasePath: `${AZURE_OPENAI_ENDPOINT}/openai/deployments`,
    timeout: 60_000,
    maxRetries: 1,
  });
}

function makeFoundryChat(deployment, apiKey) {
  return new ChatOpenAI({
    model: deployment,
    apiKey,
    timeout: 60_000,
    maxRetries: 1,
    configuration: {
      baseURL: BASE_URL,
      defaultHeaders: { "api-key": apiKey },
    },
  });
}

function makeFoundryResponsesChat(deployment, apiKey) {
  return new ChatOpenAI({
    model: deployment,
    apiKey,
    timeout: 60_000,
    maxRetries: 1,
    useResponsesApi: true,
    configuration: {
      baseURL: BASE_URL,
      defaultHeaders: { "api-key": apiKey },
    },
  });
}

function extractText(content) {
  if (content == null) return "";
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    return content
      .map((b) =>
        typeof b === "string"
          ? b
          : typeof b?.text === "string"
            ? b.text
            : ""
      )
      .join("");
  }
  return String(content);
}

// ---------------------------------------------------------------------------
// Build the multi-agent workflow for a given chat model
// ---------------------------------------------------------------------------
function buildWorkflow(chat, protocolTag) {
  // Inner data agent
  const dataAgent = createReactAgent({
    llm: chat,
    tools: [getCurrentWeather],
    prompt: DATA_INSTRUCTIONS,
  });

  // Agent-as-tool wrapper
  const weatherDataAgentTool = tool(
    async ({ cities }, config) => {
      const result = await dataAgent.invoke(
        { messages: [new HumanMessage(`Look up weather for: ${cities}`)] },
        config
      );
      const msgs = result.messages ?? [];
      for (let i = msgs.length - 1; i >= 0; i--) {
        const msg = msgs[i];
        if (
          msg instanceof AIMessage ||
          msg.constructor?.name === "AIMessage"
        ) {
          const text = extractText(msg.content);
          if (text) return text;
        }
      }
      return "";
    },
    {
      name: "weather_data_agent",
      description:
        "Delegate weather lookups to the weather data agent. Pass the list of cities.",
      schema: z.object({
        cities: z
          .string()
          .describe(
            "Semicolon- or comma-separated list of cities to look up"
          ),
      }),
    }
  );

  // Main agent
  const mainAgent = createReactAgent({
    llm: chat,
    tools: [weatherDataAgentTool],
    prompt: MAIN_INSTRUCTIONS,
  });

  // Verifier agent
  const verifierAgent = createReactAgent({
    llm: chat,
    tools: [],
    prompt: VERIFIER_INSTRUCTIONS,
  });

  // Sequential workflow
  const mainNode = async (state, config) => {
    const before = state.messages.length;
    const result = await mainAgent.invoke({ messages: state.messages }, config);
    const newMsgs = (result.messages ?? []).slice(before);
    return { messages: newMsgs };
  };

  const verifyNode = async (state, config) => {
    const before = state.messages.length;
    const result = await verifierAgent.invoke(
      { messages: state.messages },
      config
    );
    const newMsgs = (result.messages ?? []).slice(before);
    return { messages: newMsgs };
  };

  const graph = new StateGraph(MessagesAnnotation)
    .addNode("main", mainNode)
    .addNode("verify", verifyNode)
    .addEdge(START, "main")
    .addEdge("main", "verify")
    .addEdge("verify", END)
    .compile({ name: `WeatherWorkflow-${protocolTag}` });

  return graph;
}

function buildWorkflows(apiKey) {
  const workflows = [];

  try {
    const chatAz = makeAzureChat(DEPLOYMENT, apiKey);
    workflows.push({
      protocol: "completions",
      graph: buildWorkflow(chatAz, "completions"),
    });
  } catch (ex) {
    console.log(`[build] failed completions: ${ex}`);
  }

  try {
    const chatF = makeFoundryChat(DEPLOYMENT, apiKey);
    workflows.push({
      protocol: "foundry-completions",
      graph: buildWorkflow(chatF, "foundry-completions"),
    });
  } catch (ex) {
    console.log(`[build] failed foundry-completions: ${ex}`);
  }

  try {
    const chatFR = makeFoundryResponsesChat(DEPLOYMENT, apiKey);
    workflows.push({
      protocol: "foundry-responses",
      graph: buildWorkflow(chatFR, "foundry-responses"),
    });
  } catch (ex) {
    console.log(`[build] failed foundry-responses: ${ex}`);
  }

  return workflows;
}

// ---------------------------------------------------------------------------
// Run
// ---------------------------------------------------------------------------
async function runOnce(workflows, runLabel) {
  console.log(`\n=== Run: ${runLabel} ===`);
  console.log(`You: ${USER_PROMPT}\n`);

  const tasks = workflows.map(async ({ protocol, graph }) => {
    try {
      const result = await graph.invoke({
        messages: [new HumanMessage(USER_PROMPT)],
      });
      return { protocol, result };
    } catch (error) {
      return { protocol, error };
    }
  });

  const results = await Promise.all(tasks);
  let successes = 0;
  for (const r of results) {
    console.log(`--- [${r.protocol}] ---`);
    if (r.error) {
      console.log(`  Error: ${r.error?.message ?? r.error}`);
      continue;
    }
    successes += 1;

    const msgs = r.result?.messages ?? [];
    const aiTexts = [];
    for (const msg of msgs) {
      if (
        msg instanceof AIMessage ||
        msg.constructor?.name === "AIMessage"
      ) {
        const text = extractText(msg.content);
        if (text && !text.startsWith("[tool")) {
          aiTexts.push(text);
        }
      }
    }
    if (aiTexts.length >= 2) {
      console.log(`  Assistant: ${aiTexts[aiTexts.length - 2]}`);
      console.log(`  Verifier:  ${aiTexts[aiTexts.length - 1]}`);
    } else if (aiTexts.length === 1) {
      console.log(`  (single AI text): ${aiTexts[0]}`);
    }
  }
  console.log(
    `\n[${runLabel}] ${successes}/${results.length} workflows succeeded`
  );
  return successes;
}

async function main() {
  const runId = process.argv[2] ?? randomUUID();
  console.log(`Service: ${SERVICE_NAME}`);
  console.log(`RunId:   ${runId}`);

  const apiKey = process.env.AZURE_OPENAI_API_KEY ?? "";
  if (!apiKey) {
    console.error("Error: AZURE_OPENAI_API_KEY is required.");
    return 1;
  }

  const workflows = buildWorkflows(apiKey);
  console.log(`Built ${workflows.length} workflow variants.`);

  const loopForever = ["1", "true", "yes"].includes(
    (process.env.LOOP_FOREVER ?? "").toLowerCase()
  );
  const interval = Number(process.env.LOOP_INTERVAL_SECONDS ?? "60");

  let iteration = 0;
  while (true) {
    iteration += 1;
    await runOnce(workflows, `iteration-${iteration}`);
    if (!loopForever) break;
    console.log(`\nSleeping ${interval}s before next iteration...`);
    await new Promise((r) => setTimeout(r, interval * 1000));
  }

  return 0;
}

main()
  .then((code) => process.exit(code ?? 0))
  .catch((err) => {
    console.error(err);
    process.exit(1);
  });
