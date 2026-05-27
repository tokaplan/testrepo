# WeatherChatMAFPython with Microsoft OpenTelemetry distro

> # ✅ CANONICAL — MAF Python agent
>
> This is the **canonical MAF Python implementation** referenced by
> [`/AGENTS.md`](../../AGENTS.md),
> [`/CANONICAL-AGENTS.md`](../../CANONICAL-AGENTS.md), and the
> compliance matrix [`/data/agent-telemetry-compliance.md`](../../data/agent-telemetry-compliance.md).
>
> Cloud-role name: `WeatherChatMAFPython-MS-Distro`. Entry point: `main.py`.
>
> Look-alike folders (`../../WeatherChatMAFPython\`) are **legacy** and
> must not be used for matrix work — see their `> ⛔ LEGACY` banner.

---

Same MAF (Microsoft Agent Framework) Python agent as the sibling
`WeatherChatMAFPython` project. Telemetry is supplied entirely by
Microsoft's `microsoft-opentelemetry` distro — one call to
`use_microsoft_opentelemetry()` replaces all the manual setup from the
original (TracerProvider + BatchSpanProcessor + AzureMonitorTraceExporter
+ MeterProvider + OpenAIInstrumentor).

The distro auto-loads its bundled `OpenAIInstrumentor` and registers an
`AgentFrameworkSpanProcessor` (for span enrichment) via the
`opentelemetry_instrumentor` entry-point discovery against
`_SUPPORTED_INSTRUMENTED_LIBRARIES`.

**However, the distro does NOT enable MAF's own internal instrumentation
flag.** That is opt-in via either:

- `agent_framework.observability.enable_instrumentation()` (this app
  calls it explicitly), or
- the `ENABLE_INSTRUMENTATION=true` environment variable.

Without one of those, MAF's `Agent.run` never emits `invoke_agent` /
`execute_tool` spans, regardless of how OTel is configured. This is
analogous to .NET's `AppContext.SetSwitch("OpenAI.Experimental.EnableOpenTelemetry", true)`
toggle — the flag lives in the agent SDK itself, not in the OTel distro.

## Run locally

```pwsh
python -m venv .venv
. .venv/Scripts/Activate.ps1
pip install -r requirements.txt
$env:AZURE_OPENAI_API_KEY = "<your foundry key>"
python main.py
```

`cloud_RoleName` is `WeatherChatMAFPython-MS-Distro` so this run can be
filtered out from the original `WeatherChatMAFPython` data side by side.
