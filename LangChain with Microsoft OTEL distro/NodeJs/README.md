# LangChainNodeJs with Microsoft OpenTelemetry distro

Same agent as the sibling `LangChainNodeJs` project, but its only telemetry
setup is Microsoft's `@microsoft/opentelemetry` distro, loaded via
`node --import ./telemetry.mjs main.js`. The shim is a single
`useMicrosoftOpenTelemetry({ azureMonitor: ..., instrumentationOptions: { langchain: { enabled: true } } })`
call - the distro's bundled LangChain instrumentation does the rest.

## Run locally

```pwsh
npm install
$env:AZURE_OPENAI_API_KEY = "<your foundry key>"
npm start
```

`cloud_RoleName` is `LangChainNodeJs-MS-Distro` so this run can be filtered
out from the original `LangChainNodeJs` data side by side.
