import "@microsoft/opentelemetry/loader";
import { useMicrosoftOpenTelemetry } from "@microsoft/opentelemetry";
import { resourceFromAttributes } from "@opentelemetry/resources";
import { AsyncLocalStorage } from "node:async_hooks";

const SERVICE_NAME = "LangChainNodeJs-MS-Distro";
const RUN_ID = process.argv[2] ?? "";

// Belt-and-suspenders: also set service.name via env var so the OTel
// envDetector picks it up regardless of whether `resource:` makes it through
// the distro's option-merging path.
process.env.OTEL_SERVICE_NAME ??= SERVICE_NAME;

// Stamp test.runId / test.protocol on every span so the matrix KQL can
// distinguish (client class, API) permutations side by side. Protocol comes
// from an AsyncLocalStorage that main.js sets per agent invocation via
// globalThis.__setTestProtocol(...).
const protocolStore = new AsyncLocalStorage();
globalThis.__setTestProtocol = (protocol, fn) => protocolStore.run(protocol, fn);

class TestTaggingSpanProcessor {
  onStart(span) {
    try {
      span.setAttribute("test.agent", SERVICE_NAME);
      if (RUN_ID) span.setAttribute("test.runId", RUN_ID);
      const proto = protocolStore.getStore();
      if (proto) span.setAttribute("test.protocol", proto);
    } catch (e) {
      // never let tagging break the pipeline
      console.error("[telemetry.mjs] tagging error:", e);
    }
  }
  onEnd(_span) {}
  shutdown() { return Promise.resolve(); }
  forceFlush() { return Promise.resolve(); }
}

const DEFAULT_APP_INSIGHTS_CONNECTION_STRING =
  "InstrumentationKey=06533fcd-4317-4b63-9c52-a518c492d907;" +
  "IngestionEndpoint=https://eastus2-3.in.applicationinsights.azure.com/;" +
  "LiveEndpoint=https://eastus2.livediagnostics.monitor.azure.com/;" +
  "ApplicationId=66a40307-82d6-4baf-8886-37141dc8d391";

useMicrosoftOpenTelemetry({
  resource: resourceFromAttributes({ "service.name": SERVICE_NAME }),
  spanProcessors: [new TestTaggingSpanProcessor()],
  azureMonitor: {
    azureMonitorExporterOptions: {
      connectionString:
        process.env.APPLICATIONINSIGHTS_CONNECTION_STRING ??
        DEFAULT_APP_INSIGHTS_CONNECTION_STRING,
    },
    enableLiveMetrics: false,
  },
  // NOTE: explicit langchain flag is required in 0.1.0-beta.1 (defaults bug).
  instrumentationOptions: {
    langchain: { enabled: true },
  },
});

console.error(`[telemetry.mjs] init: service=${SERVICE_NAME}, runId=${RUN_ID || "(none)"}`);
