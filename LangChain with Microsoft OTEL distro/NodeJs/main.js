/**
 * LangChainNodeJs with Microsoft OpenTelemetry distro - multi-agent topology
 * (agent-as-tool + sequential workflow) mirroring the LangChain Python agent.
 *
 * Topology per protocol:
 *
 *     StateGraph (sequential workflow)
 *     +- MainAgent (createReactAgent, tools=[weatherDataAgent])
 *     |  +- weatherDataAgent  <-- tool() wrapping inner DataAgent (agent-as-tool)
 *     |     +- DataAgent (createReactAgent, tools=[getCurrentWeather])
 *     +- VerifierAgent (createReactAgent, tools=[], streaming)
 *
 * The Verifier agent's chat client is built with `streaming: true` so that at
 * least one sub-agent uses streaming while the other two stay non-streaming,
 * mirroring the sibling LC Python multi-agent flow. All three agents are
 * wrapped with createReactAgent so each emits its own invoke_agent span
 * (parity with LC Python's create_agent(...) and MAF's Agent(...)).
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
import { shutdownMicrosoftOpenTelemetry } from "@microsoft/opentelemetry";

const ENDPOINT =
  "https://alkap-mc9jji6o-eastus2.services.ai.azure.com/api/projects/alkap-mc9jji6o-eastus2_project";
const BASE_URL = ENDPOINT + "/openai/v1/";
const AZURE_OPENAI_ENDPOINT =
  "https://alkap-mc9jji6o-eastus2.cognitiveservices.azure.com";
const AZURE_OPENAI_API_VERSION = "2025-04-01-preview";

// Per-role deployments. One workflow per protocol exercises three distinct
// models (data, main, verifier).
const AGENT_DEPLOYMENTS = {
  data: "deployment-gpt-4o-mini",
  main: "deployment-gpt-5.4-mini",
  verifier: "deployment-gpt-4o",
};

const SERVICE_NAME = "LangChainNodeJs-MS-Distro";
const USER_PROMPT = "What's the weather like in Seattle and San Francisco?";

const DATA_AGENT_DESCRIPTION =
  "Weather data sub-agent that looks up current conditions for one or more " +
  "cities via the get_current_weather tool.";
const MAIN_AGENT_DESCRIPTION =
  "Main weather assistant that delegates lookups to the weather data " +
  "sub-agent and summarizes the result for the end user.";
const VERIFIER_AGENT_DESCRIPTION =
  "Verifier agent that sanity-checks the main assistant's reply for " +
  "hallucinated cities, impossible weather, and missing cities.";

const DATA_INSTRUCTIONS =
  "You are a weather data agent. You look up weather information for " +
  "one or more cities using the get_current_weather tool. " +
  "Call the tool ONCE per requested city, then return a concise JSON-like " +
  "string containing all results. Do not add any commentary.";

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
        .enum(["fahrenheit", "celsius"])
        .optional()
        .describe("The temperature unit (defaults to fahrenheit)"),
    }),
  }
);

// ---------------------------------------------------------------------------
// Chat client factories
// ---------------------------------------------------------------------------
function makeAzureChat(deployment, apiKey, streaming = false) {
  return new AzureChatOpenAI({
    azureOpenAIApiKey: apiKey,
    azureOpenAIApiInstanceName: "alkap-mc9jji6o-eastus2",
    azureOpenAIApiDeploymentName: deployment,
    azureOpenAIApiVersion: AZURE_OPENAI_API_VERSION,
    azureOpenAIBasePath: `${AZURE_OPENAI_ENDPOINT}/openai/deployments`,
    timeout: 60_000,
    maxRetries: 1,
    streaming,
  });
}

function makeFoundryChat(deployment, apiKey, streaming = false) {
  return new ChatOpenAI({
    model: deployment,
    apiKey,
    timeout: 60_000,
    maxRetries: 1,
    streaming,
    configuration: {
      baseURL: BASE_URL,
      defaultHeaders: { "api-key": apiKey },
    },
  });
}

function makeFoundryResponsesChat(deployment, apiKey, streaming = false) {
  return new ChatOpenAI({
    model: deployment,
    apiKey,
    timeout: 60_000,
    maxRetries: 1,
    useResponsesApi: true,
    streaming,
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
// Multi-agent workflow per protocol
// ---------------------------------------------------------------------------
function buildWorkflow(dataChat, mainChat, verifierChat, protocolTag) {
  // Per-workflow agent IDs so each run gets fresh, distinct gen_ai.agent.id
  // values for Data, Main, and Verifier, propagated through per-invoke
  // RunnableConfig metadata. (The JS distro's LangChain instrumentor reads
  // gen_ai.agent.name from the LangGraph run name, set here via
  // createReactAgent({ name }).)
  const dataAgentId = randomUUID();
  const mainAgentId = randomUUID();
  const verifierAgentId = randomUUID();
  const dataMeta = {
    agent_id: dataAgentId,
    agent_description: DATA_AGENT_DESCRIPTION,
  };
  const mainMeta = {
    agent_id: mainAgentId,
    agent_description: MAIN_AGENT_DESCRIPTION,
  };
  const verifierMeta = {
    agent_id: verifierAgentId,
    agent_description: VERIFIER_AGENT_DESCRIPTION,
  };

  // Inner data agent — has the raw weather tool.
  const dataAgent = createReactAgent({
    llm: dataChat,
    tools: [getCurrentWeather],
    name: `WeatherDataAgent-${protocolTag}`,
    description: DATA_AGENT_DESCRIPTION,
  });

  // Wrap data agent as a tool so the main agent can delegate to it.
  const weatherDataAgent = tool(
    async ({ cities }, config) => {
      // Override the parent (main) agent's metadata with this nested agent's
      // own id/description so its invoke_agent span carries the data role's
      // identity, not main's.
      const nestedConfig = {
        ...(config ?? {}),
        metadata: { ...(config?.metadata ?? {}), ...dataMeta },
      };
      const result = await dataAgent.invoke(
        {
          messages: [
            new SystemMessage(DATA_INSTRUCTIONS),
            new HumanMessage(`Look up weather for: ${cities}`),
          ],
        },
        nestedConfig
      );
      const messages = result.messages ?? [];
      for (let i = messages.length - 1; i >= 0; i--) {
        const msg = messages[i];
        if (msg instanceof AIMessage || msg.constructor?.name === "AIMessage") {
          const text = extractText(msg.content);
          if (text) return text;
        }
      }
      return "";
    },
    {
      name: "weather_data_agent",
      description: "Delegate weather lookups to the weather data agent.",
      schema: z.object({
        cities: z
          .string()
          .describe(
            "Semicolon- or comma-separated list of cities to look up."
          ),
      }),
    }
  );

  // Main agent — has the data-agent-as-tool.
  const mainAgent = createReactAgent({
    llm: mainChat,
    tools: [weatherDataAgent],
    name: `MainWeatherAgent-${protocolTag}`,
    description: MAIN_AGENT_DESCRIPTION,
  });

  // Verifier agent — no tools, but wrapped with createReactAgent so it emits
  // its own invoke_agent span (parity with LC Python's create_agent and
  // MAF's Agent). The underlying chat client is streaming.
  const verifierAgent = createReactAgent({
    llm: verifierChat,
    tools: [],
    name: `VerifierAgent-${protocolTag}`,
    description: VERIFIER_AGENT_DESCRIPTION,
  });

  async function mainNode(state, config) {
    const before = state.messages.length;
    const invokeConfig = {
      ...(config ?? {}),
      metadata: { ...(config?.metadata ?? {}), ...mainMeta },
    };
    const result = await mainAgent.invoke(
      {
        messages: [new SystemMessage(MAIN_INSTRUCTIONS), ...state.messages],
      },
      invokeConfig
    );
    // mainAgent.invoke returns the full message list including our system
    // prompt + prior user message; skip the (before+1) we passed in.
    const newMsgs = (result.messages ?? []).slice(before + 1);
    return { messages: newMsgs };
  }

  async function verifyNode(state, config) {
    const before = state.messages.length;
    const invokeConfig = {
      ...(config ?? {}),
      metadata: { ...(config?.metadata ?? {}), ...verifierMeta },
    };
    const result = await verifierAgent.invoke(
      {
        messages: [
          new SystemMessage(VERIFIER_INSTRUCTIONS),
          ...state.messages,
        ],
      },
      invokeConfig
    );
    // Like mainNode: skip the system prompt + the (before) state messages we
    // passed in, returning only the verifier's new AI message(s).
    const newMsgs = (result.messages ?? []).slice(before + 1);
    return { messages: newMsgs };
  }

  const graph = new StateGraph(MessagesAnnotation)
    .addNode("main", mainNode)
    .addNode("verify", verifyNode)
    .addEdge(START, "main")
    .addEdge("main", "verify")
    .addEdge("verify", END)
    .compile();

  return graph;
}

function buildWorkflows(apiKey) {
  const workflows = [];

  const factories = {
    completions: (deployment, streaming) =>
      makeAzureChat(deployment, apiKey, streaming),
    "foundry-completions": (deployment, streaming) =>
      makeFoundryChat(deployment, apiKey, streaming),
    "foundry-responses": (deployment, streaming) =>
      makeFoundryResponsesChat(deployment, apiKey, streaming),
  };

  for (const protocol of [
    "completions",
    "foundry-completions",
    "foundry-responses",
  ]) {
    try {
      const make = factories[protocol];
      const dataChat = make(AGENT_DEPLOYMENTS.data, false);
      const mainChat = make(AGENT_DEPLOYMENTS.main, false);
      // Verifier streams so each workflow has both streaming and
      // non-streaming sub-agents (matches LC Python topology).
      const verifierChat = make(AGENT_DEPLOYMENTS.verifier, true);
      workflows.push({
        protocol,
        graph: buildWorkflow(dataChat, mainChat, verifierChat, protocol),
      });
    } catch (ex) {
      console.log(`[build] failed ${protocol}: ${ex}`);
    }
  }

  return workflows;
}

// ---------------------------------------------------------------------------
// Run
// ---------------------------------------------------------------------------
async function runOnce(workflows, runLabel) {
  console.log(`\n=== Run: ${runLabel} ===`);
  console.log(`You: ${USER_PROMPT}\n`);

  // The optional globalThis.__setTestProtocol shim is installed by
  // telemetry.mjs (when running under `--import ./telemetry.mjs`). It tags
  // every span produced inside fn() with the supplied protocol. When the
  // shim is absent (e.g. running without the bootstrap), fall through.
  const setProto = globalThis.__setTestProtocol ?? ((_p, fn) => fn());

  const sequential = ["1", "true", "yes"].includes(
    (process.env.SEQUENTIAL ?? "").toLowerCase()
  );

  async function runOne({ protocol, graph }) {
    return setProto(protocol, async () => {
      try {
        // One conversation per workflow run. The Microsoft OTEL distro's
        // LangChain instrumentor reads `metadata.conversation_id` and emits
        // it as `gen_ai.conversation.id` on every span (note: it reads
        // session_id/thread_id only for the separate microsoft.session_id
        // attribute). LangGraph propagates metadata down the run tree, so
        // setting it once at the top invocation covers all child runs.
        const conversationId = randomUUID();
        const result = await graph.invoke(
          {
            messages: [new HumanMessage(USER_PROMPT)],
          },
          { metadata: { conversation_id: conversationId } }
        );
        return { protocol, result };
      } catch (error) {
        return { protocol, error };
      }
    });
  }

  let results;
  if (sequential) {
    results = [];
    for (const wf of workflows) {
      results.push(await runOne(wf));
    }
  } else {
    results = await Promise.all(workflows.map(runOne));
  }

  let successes = 0;
  for (const r of results) {
    console.log(`--- [${r.protocol}] ---`);
    if (r.error) {
      console.log(`  Error: ${r.error?.message ?? r.error}`);
      continue;
    }
    successes += 1;

    const msgs = r.result?.messages ?? [];
    // Last AIMessage is the verifier's response; the AIMessage before any
    // verifier output is the main agent's final assistant message.
    const aiTexts = [];
    for (const msg of msgs) {
      if (msg instanceof AIMessage || msg.constructor?.name === "AIMessage") {
        const text = extractText(msg.content);
        if (text && !text.startsWith("[tool")) {
          aiTexts.push(text);
        }
      }
    }
    const verifier = aiTexts[aiTexts.length - 1] ?? "";
    const assistant = aiTexts[aiTexts.length - 2] ?? "";
    if (assistant) console.log(`  Assistant: ${assistant}`);
    if (verifier) console.log(`  Verifier:  ${verifier}`);
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

  console.log(`Agent deployments:`, AGENT_DEPLOYMENTS);
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
  .then(async (code) => {
    // Flush any pending spans before exit. Without this, the final protocol's
    // spans (which run last under SEQUENTIAL=1) can be dropped if the
    // BatchSpanProcessor hasn't flushed yet.
    try {
      await shutdownMicrosoftOpenTelemetry();
    } catch (err) {
      console.error("[main] shutdown error:", err);
    }
    process.exit(code ?? 0);
  })
  .catch(async (err) => {
    console.error(err);
    try {
      await shutdownMicrosoftOpenTelemetry();
    } catch {}
    process.exit(1);
  });
