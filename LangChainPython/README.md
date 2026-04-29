# LangChainPython

LangChain.py port of `WeatherChatMAFPython`. Hits the same Azure AI Foundry
endpoint, the same deployments, uses the same `get_current_weather` tool, and
exports OTEL traces and metrics to Application Insights with the same
`test.agent` / `test.runId` / `test.protocol` span attributes.

LangChain's stable cross-provider abstraction is Chat Completions, so every
deployment is exercised through Chat Completions (Azure OpenAI endpoint and
the Foundry `/openai/v1/` base URL). LangChain does not have first-class
Azure Responses API support, so the Responses-API variant from the MAF apps
is not duplicated here.

## Run locally

```pwsh
python -m venv .venv
. .venv/Scripts/Activate.ps1
pip install -r requirements.txt
$env:AZURE_OPENAI_API_KEY = "<your foundry key>"
python main.py
```

Set `LOOP_FOREVER=1` to keep the agent running and re-asking the prompt every
`LOOP_INTERVAL_SECONDS` seconds (used in the Kubernetes deployment).

Set `APPLICATIONINSIGHTS_CONNECTION_STRING` to override the default App
Insights destination.

## Build container

```pwsh
docker build -t aicommon.azurecr.io/alkaplan/langchain-python:1 .
docker push aicommon.azurecr.io/alkaplan/langchain-python:1
```

## Deploy to AKS

```pwsh
# Edit k8s/namespace-secret-instrumentation.yaml first to set the API key and
# Application Insights connection string.
kubectl apply -f k8s/namespace-secret-instrumentation.yaml
kubectl apply -f k8s/deployment.yaml
```

The deployment carries the
`instrumentation.opentelemetry.io/private-preview-inject-python: "default"`
annotation so the AKS App Monitoring webhook injects the Microsoft Python
OpenTelemetry distro (init container `azure-monitor-auto-instrumentation-python`).
Python is private preview at api-version 2026-02-01, which is why a different
annotation key (`private-preview-inject-python`) is used than the GA Java/NodeJs
counterparts (`inject-java` / `inject-nodejs`). The Instrumentation CR's
`autoInstrumentationPlatforms` enum still only accepts `Java`/`NodeJs`; Python
is enabled solely via the per-workload annotation.

The container's own manual OTEL setup also exports to
`APPLICATIONINSIGHTS_CONNECTION_STRING`, so telemetry lands in App Insights
twice: once from auto-instrumentation, once from the manual exporter wired up
in `main.py`.
