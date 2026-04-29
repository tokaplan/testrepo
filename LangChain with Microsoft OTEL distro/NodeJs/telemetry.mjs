// Bootstrap shim that registers Microsoft's OpenTelemetry distro before
// main.js loads any LangChain / OpenAI module. Loaded via:
//   node --import ./telemetry.mjs main.js
// (See @microsoft/opentelemetry README "ESM Support" section.)

import "@microsoft/opentelemetry/loader";
import { useMicrosoftOpenTelemetry } from "@microsoft/opentelemetry";

const DEFAULT_APP_INSIGHTS_CONNECTION_STRING =
  "InstrumentationKey=06533fcd-4317-4b63-9c52-a518c492d907;" +
  "IngestionEndpoint=https://eastus2-3.in.applicationinsights.azure.com/;" +
  "LiveEndpoint=https://eastus2.livediagnostics.monitor.azure.com/;" +
  "ApplicationId=66a40307-82d6-4baf-8886-37141dc8d391";

useMicrosoftOpenTelemetry({
  azureMonitor: {
    azureMonitorExporterOptions: {
      connectionString:
        process.env.APPLICATIONINSIGHTS_CONNECTION_STRING ??
        DEFAULT_APP_INSIGHTS_CONNECTION_STRING,
    },
    enableLiveMetrics: false,
  },
  instrumentationOptions: {
    langchain: { enabled: true },
  },
});
