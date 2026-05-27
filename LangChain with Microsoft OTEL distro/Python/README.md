# LangChainPython with Microsoft OpenTelemetry distro

> # ✅ CANONICAL — LangChain Python agent
>
> This is the **canonical LangChain Python implementation** referenced by
> [`/AGENTS.md`](../../AGENTS.md),
> [`/CANONICAL-AGENTS.md`](../../CANONICAL-AGENTS.md), and the
> compliance matrix [`/data/agent-telemetry-compliance.md`](../../data/agent-telemetry-compliance.md).
>
> Cloud-role name: `WeatherChatLangChain-MS-Distro`. Entry point: `main.py`.
>
> Look-alike folders (`../../LangChainPython\`,
> `../../WeatherChatPython\`) are **legacy** and must not be used for
> matrix work — see their `> ⛔ LEGACY` banner.

---

Same agent as the sibling `LangChainPython` project. Telemetry is supplied
by an out-of-tree instrumentation setup - this folder ships only the agent
code itself.

To wire up Microsoft's `microsoft-opentelemetry` distro and emit `gen_ai.*`
spans to Application Insights, add the following on top of `requirements.txt`
and `main.py` outside of source control:

- requirements.txt: `microsoft-opentelemetry`
- main.py: at the start of `main()`,
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

That single call replaces what a full setup with
`opentelemetry-instrumentation-openai-v2` +
`opentelemetry-instrumentation-langchain` + Azure Monitor exporter would
otherwise need.

## Run locally

```pwsh
python -m venv .venv
. .venv/Scripts/Activate.ps1
pip install -r requirements.txt
$env:AZURE_OPENAI_API_KEY = "<your foundry key>"
python main.py
```

`cloud_RoleName` is `LangChainPython-MS-Distro` so this run can be
filtered out from the original `LangChainPython` data side by side.
