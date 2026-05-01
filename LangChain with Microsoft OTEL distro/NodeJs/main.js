/**
 * LangChainNodeJs with Microsoft OpenTelemetry distro.
 *
 * Same agent as the sibling LangChainNodeJs project, but its only telemetry
 * setup is Microsoft's `@microsoft/opentelemetry` distro, loaded via
 * `node --import ./telemetry.mjs main.js`. No instrumentation registration
 * in this file - the distro turns on its bundled LangChain + OpenAI Agents
 * instrumentations by default.
 */

import { AzureChatOpenAI, ChatOpenAI } from "@langchain/openai";
import { tool } from "@langchain/core/tools";
import {
  AIMessage,
  HumanMessage,
  SystemMessage,
} from "@langchain/core/messages";
import { createReactAgent } from "@langchain/langgraph/prebuilt";
import { z } from "zod";

import { randomUUID } from "node:crypto";
import process from "node:process";

const ENDPOINT =
  "https://alkap-mc9jji6o-eastus2.services.ai.azure.com/api/projects/alkap-mc9jji6o-eastus2_project";
const BASE_URL = ENDPOINT + "/openai/v1/";
const AZURE_OPENAI_ENDPOINT =
  "https://alkap-mc9jji6o-eastus2.cognitiveservices.azure.com";
const AZURE_OPENAI_API_VERSION = "2025-04-01-preview";

const DEPLOYMENT_NAMES = [
  "deployment-gpt-5.4-mini",
  "deployment-gpt-4o",
  "deployment-gpt-4o-mini",
  "deployment-o4-mini",
  "deployment-Phi-4",
  "deployment-DeepSeek-R1",
  "deployment-Llama-3.3-70B-Instruct",
];

const NO_TOOL_DEPLOYMENTS = new Set([
  "deployment-Phi-4",
  "deployment-DeepSeek-R1",
]);

const SERVICE_NAME = "LangChainNodeJs-MS-Distro";
const USER_PROMPT = "What's the weather like in Seattle and San Francisco?";

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

function instructions(useTools) {
  return (
    "You are a helpful weather assistant. " +
    (useTools
      ? "Use the get_current_weather tool to look up weather information when asked."
      : "Answer weather questions using your knowledge. You do not have access to tools.")
  );
}

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

function buildAgentRunner(chat, useTools) {
  const sys = instructions(useTools);

  if (useTools) {
    const agent = createReactAgent({
      llm: chat,
      tools: [getCurrentWeather],
    });

    return async (userPrompt) => {
      const result = await agent.invoke({
        messages: [new SystemMessage(sys), new HumanMessage(userPrompt)],
      });
      const messages = result.messages ?? [];
      for (let i = messages.length - 1; i >= 0; i--) {
        const msg = messages[i];
        if (msg instanceof AIMessage || msg.constructor?.name === "AIMessage") {
          const text = extractText(msg.content);
          if (text) return text;
        }
      }
      return "";
    };
  }

  return async (userPrompt) => {
    const response = await chat.invoke([
      new SystemMessage(sys),
      new HumanMessage(userPrompt),
    ]);
    return extractText(response.content);
  };
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

function buildAgents(apiKey) {
  const agents = [];
  for (const deployment of DEPLOYMENT_NAMES) {
    const useTools = !NO_TOOL_DEPLOYMENTS.has(deployment);

    try {
      const chatAz = makeAzureChat(deployment, apiKey);
      agents.push({
        label: `${deployment} [completions]`,
        protocol: "completions",
        run: buildAgentRunner(chatAz, useTools),
      });
    } catch (ex) {
      console.log(`[build] failed completions ${deployment}: ${ex}`);
    }

    if (useTools) {
      try {
        const chatF = makeFoundryChat(deployment, apiKey);
        agents.push({
          label: `${deployment} [foundry-completions]`,
          protocol: "foundry-completions",
          run: buildAgentRunner(chatF, useTools),
        });
      } catch (ex) {
        console.log(`[build] failed foundry ${deployment}: ${ex}`);
      }

      try {
        const chatFR = makeFoundryResponsesChat(deployment, apiKey);
        agents.push({
          label: `${deployment} [foundry-responses]`,
          protocol: "foundry-responses",
          run: buildAgentRunner(chatFR, useTools),
        });
      } catch (ex) {
        console.log(`[build] failed foundry-responses ${deployment}: ${ex}`);
      }
    }
  }
  return agents;
}

async function runOnce(agents, runLabel) {
  console.log(`\n=== Run: ${runLabel} ===`);
  console.log(`You: ${USER_PROMPT}\n`);

  // The optional globalThis.__setTestProtocol shim is installed by
  // telemetry.mjs (when running under `--import ./telemetry.mjs`). It tags
  // every span produced inside fn() with the supplied protocol. When the
  // shim is absent (e.g. running without the bootstrap), fall through.
  const setProto = globalThis.__setTestProtocol ?? ((_p, fn) => fn());

  const tasks = agents.map(async ({ label, protocol, run }) =>
    setProto(protocol, async () => {
      try {
        const text = await run(USER_PROMPT);
        return { label, text };
      } catch (error) {
        return { label, error };
      }
    })
  );

  const results = await Promise.all(tasks);
  let successes = 0;
  for (const r of results) {
    console.log(`--- [${r.label}] ---`);
    if (r.error) {
      console.log(`  Error: ${r.error?.message ?? r.error}`);
      continue;
    }
    successes += 1;
    if (r.text) console.log(`  Assistant: ${r.text}`);
  }
  console.log(
    `\n[${runLabel}] ${successes}/${results.length} agents succeeded`
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

  const agents = buildAgents(apiKey);
  console.log(`Built ${agents.length} agent variants.`);

  const loopForever = ["1", "true", "yes"].includes(
    (process.env.LOOP_FOREVER ?? "").toLowerCase()
  );
  const interval = Number(process.env.LOOP_INTERVAL_SECONDS ?? "60");

  let iteration = 0;
  while (true) {
    iteration += 1;
    await runOnce(agents, `iteration-${iteration}`);
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
