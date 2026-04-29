# LangChainPython with Microsoft OpenTelemetry distro

Same agent as the sibling `LangChainPython` project, but its only telemetry
setup is the Microsoft distro:

```python
from microsoft.opentelemetry import use_microsoft_opentelemetry
use_microsoft_opentelemetry(
    enable_azure_monitor=True,
    azure_monitor_connection_string=...,
    instrumentation_options={
        "langchain": {"enabled": True},
        "openai": {"enabled": True},
    },
)
```

That single call replaces what previously required separate
`opentelemetry-instrumentation-openai-v2` +
`opentelemetry-instrumentation-langchain` + Azure Monitor exporter wiring.

## Run locally

```pwsh
python -m venv .venv
. .venv/Scripts/Activate.ps1
pip install -r requirements.txt
$env:AZURE_OPENAI_API_KEY = "<your foundry key>"
python main.py
```

The agent logs to Application Insights `data-1` in `alkaplan-longchain` by
default (or wherever `APPLICATIONINSIGHTS_CONNECTION_STRING` points).

`cloud_RoleName` is `LangChainPython-MS-Distro` so this run can be filtered
out from the original `LangChainPython` data side by side.
