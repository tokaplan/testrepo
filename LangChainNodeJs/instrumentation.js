/**
 * Bootstrap shim that wires OpenAI + LangChain instrumentation packages
 * into the OpenTelemetry global TracerProvider that the AKS App Monitoring
 * Node.js auto-instrumentation distro installed at process start.
 *
 * Loaded via `node --import ./instrumentation.js main.js` so registration
 * happens BEFORE main.js imports the OpenAI / LangChain packages.
 *
 * Wires up two off-the-shelf instrumentation packages:
 *   - @traceloop/instrumentation-openai - chat-level GenAI spans
 *     (gen_ai.system, gen_ai.request.model, gen_ai.usage.*,
 *     gen_ai.prompt.*, gen_ai.completion.*) for every OpenAI Node SDK call.
 *   - @traceloop/instrumentation-langchain @ 0.14.6 - the last release that
 *     does NOT patch langsmith. It hooks `RunnableSequence.invoke`,
 *     `BaseChain.call`, `AgentExecutor._call`, `Tool.call`,
 *     `VectorStoreRetriever._getRelevantDocuments`. With LangChain 0.3.x +
 *     langgraph the most relevant patches are RunnableSequence/Tool, which
 *     create proper parent spans that the openai.chat child spans nest
 *     under for trace correlation.
 *
 *   Newer Traceloop langchain releases (0.18.0+) added langsmith patching
 *   that breaks @langchain/langgraph's createReactAgent with
 *   "RunTree is not a constructor".
 */

import { register } from "node:module";
import { pathToFileURL } from "node:url";
register("import-in-the-middle/hook.mjs", pathToFileURL("./"), {
  data: { include: ["openai"] },
});

import { registerInstrumentations } from "@opentelemetry/instrumentation";
import { OpenAIInstrumentation } from "@traceloop/instrumentation-openai";
import { LangChainInstrumentation } from "@traceloop/instrumentation-langchain";

// Manually pass the LangChain modules to the Traceloop instrumentation - it
// patches their CJS prototypes. ESM-only consumers (us) need to provide the
// modules ourselves because 0.14.6's auto-discovery looks for `.cjs` files.
import * as runnablesModule from "@langchain/core/runnables";
import * as toolsModule from "@langchain/core/tools";

const langchainInstrumentation = new LangChainInstrumentation();
langchainInstrumentation.manuallyInstrument({
  runnablesModule,
  toolsModule,
});

registerInstrumentations({
  instrumentations: [new OpenAIInstrumentation(), langchainInstrumentation],
});
