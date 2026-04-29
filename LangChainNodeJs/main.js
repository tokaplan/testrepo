/**
 * LangChainNodeJs - LangChain.js port of WeatherChatMAF.
 *
 * All telemetry comes from AKS App Monitoring auto-instrumentation (the
 * Microsoft Node.js OTEL distro injected by the
 * `azure-monitor-auto-instrumentation-nodejs` init container). The only
 * in-code instrumentation kept here is a SpanProcessor that stamps the same
 * `test.agent` / `test.runId` / `test.protocol` attributes that
 * WeatherChatMAFPython puts on every span, so the data lines up across runs.
 *
 * When run locally (no auto-instrumentation), no telemetry is exported. The
 * agent itself still works.
 */

import { SpanKind, trace } from "@opentelemetry/api";

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

// ---------------------------------------------------------------------------
// Configuration - mirrors WeatherChatMAFPython exactly
// ---------------------------------------------------------------------------
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

const SERVICE_NAME = "LangChainNodeJs";
const GENAI_SOURCE_NAME = "LangChainNodeJs.GenAI";
const USER_PROMPT = "What's the weather like in Seattle and San Francisco?";

// ---------------------------------------------------------------------------
// Custom-attribute helper
// ---------------------------------------------------------------------------
//
// AKS App Monitoring's Node.js distro registers an OpenTelemetry SDK 2.x
// NodeTracerProvider as the global delegate. SDK 2.x removed
// `addSpanProcessor`, so we cannot post-hoc attach a processor that stamps
// every span. Instead we stamp `test.agent` / `test.runId` / `test.protocol`
// directly on the parent span we create per agent invocation - child spans
// produced by the auto-instrumented http/openai libraries inherit the same
// trace/operationId for correlation.
function stampTestAttrs(span, agentName, runId, protocol) {
  span.setAttribute("test.agent", agentName);
  span.setAttribute("test.runId", runId);
  if (protocol) span.setAttribute("test.protocol", protocol);
}

// ---------------------------------------------------------------------------
// Weather tool
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
        .enum(["fahrenheit", "celsius"])
        .optional()
        .describe("The temperature unit (defaults to fahrenheit)"),
    }),
  }
);

// ---------------------------------------------------------------------------
// Agent construction
// ---------------------------------------------------------------------------
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

// ChatOpenAI configured to use the OpenAI Responses API
// (POST /openai/v1/responses) against the Foundry endpoint.
//
// This is the only path in our setup that supports the Responses API:
// LangChain's `AzureChatOpenAI` + `useResponsesApi: true` is currently broken
// against the Azure OpenAI endpoint (returns 405 - see
// langchain-ai/langchain#31653), but pointing a plain `ChatOpenAI` at the
// Foundry `/openai/v1/` base URL routes successfully to `/openai/v1/responses`.
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

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------
async function runOnce(agents, runId, runLabel) {
  const tracer = trace.getTracer(GENAI_SOURCE_NAME);
  console.log(`\n=== Run: ${runLabel} ===`);
  console.log(`You: ${USER_PROMPT}\n`);

  const tasks = agents.map(async ({ label, protocol, run }) => {
    return await tracer.startActiveSpan(
      `langchain.agent.${label}`,
      { kind: SpanKind.INTERNAL },
      async (span) => {
        stampTestAttrs(span, SERVICE_NAME, runId, protocol);
        span.setAttribute("agent.label", label);
        span.setAttribute("agent.protocol", protocol);
        try {
          const text = await run(USER_PROMPT);
          span.setAttribute("agent.success", true);
          span.end();
          return { label, text };
        } catch (error) {
          span.setAttribute("agent.success", false);
          span.setAttribute("agent.error", String(error).slice(0, 512));
          span.end();
          return { label, error };
        }
      }
    );
  });

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
    await runOnce(agents, runId, `iteration-${iteration}`);
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
