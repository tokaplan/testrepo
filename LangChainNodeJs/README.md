# LangChainNodeJs

LangChain.js port of `WeatherChatMAF`. Hits the same Azure AI Foundry
endpoint, the same deployments, uses the same `get_current_weather` tool.

All telemetry comes from AKS App Monitoring auto-instrumentation (the
Microsoft Node.js OTEL distro injected by the
`azure-monitor-auto-instrumentation-nodejs` init container). The only
in-code instrumentation is `span.setAttribute("test.agent" / "test.runId"
/ "test.protocol", ...)` calls on the parent agent span we create per
invocation, so the data lines up across runs alongside the MAF runs. No
manual exporters, no `@azure/monitor-opentelemetry-exporter`, no
`@opentelemetry/sdk-*` setup - everything else comes from
auto-instrumentation.

> Note: the OpenTelemetry JS SDK 2.x that the AKS distro installs as the
> global `TracerProvider` no longer exposes `addSpanProcessor`, so unlike the
> Python sibling we cannot stamp the test attributes via a `SpanProcessor` -
> instead we stamp them directly on the parent agent span we create.

LangChain's stable cross-provider abstraction is Chat Completions, so every
deployment is exercised through Chat Completions (Azure OpenAI endpoint and
the Foundry `/openai/v1/` base URL). LangChain does not have first-class
Azure Responses API support, so the Responses-API variant from the MAF apps
is not duplicated here.

## Run locally

```pwsh
npm install
$env:AZURE_OPENAI_API_KEY = "<your foundry key>"
node main.js
```

Without auto-instrumentation in the environment no telemetry is exported;
the agent itself still runs.

Set `LOOP_FOREVER=1` to keep the agent running and re-asking the prompt every
`LOOP_INTERVAL_SECONDS` seconds (used in the Kubernetes deployment).

## Build container

```pwsh
docker build -t aicommon.azurecr.io/alkaplan/langchain-nodejs:4 .
docker push aicommon.azurecr.io/alkaplan/langchain-nodejs:4
```

## Deploy to AKS

```pwsh
# The shared namespace/secret/Instrumentation CR live under the LangChainPython
# folder; apply that first if it isn't already in the cluster.
kubectl apply -f ../LangChainPython/k8s/namespace-secret-instrumentation.yaml
kubectl apply -f k8s/deployment.yaml
```

The deployment carries the
`instrumentation.opentelemetry.io/inject-nodejs: "true"` annotation so the
AKS App Monitoring webhook injects the Microsoft Node.js OpenTelemetry distro
(init container `azure-monitor-auto-instrumentation-nodejs`).

