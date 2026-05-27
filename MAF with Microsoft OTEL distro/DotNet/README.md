# WeatherChatMAF with Microsoft OpenTelemetry distro

> # ✅ CANONICAL — MAF .NET agent
>
> This is the **canonical MAF .NET implementation** referenced by
> [`/AGENTS.md`](../../AGENTS.md),
> [`/CANONICAL-AGENTS.md`](../../CANONICAL-AGENTS.md), and the
> compliance matrix [`/data/agent-telemetry-compliance.md`](../../data/agent-telemetry-compliance.md).
>
> Cloud-role name: `WeatherChatMAF-MS-Distro`. Entry point: `Program.cs`.
> Project: `WeatherChatMAF.MSDistro.csproj`.
>
> Look-alike folders (`../../WeatherChatMAF\`) are **legacy** and must
> not be used for matrix work — see their `> ⛔ LEGACY` banner.

---

Same MAF (Microsoft Agent Framework) console app as the sibling
`WeatherChatMAF` .NET project. Telemetry is supplied entirely by
Microsoft's `Microsoft.OpenTelemetry` distro
([opentelemetry-distro-dotnet](https://github.com/microsoft/opentelemetry-distro-dotnet)) —
one call to `OpenTelemetrySdk.Create(otel => otel.UseMicrosoftOpenTelemetry(...))`
replaces every `AddSource(...)`, `AddAzureMonitorTraceExporter(...)`,
`AddRuntimeInstrumentation()`, etc. from the original.

The distro auto-instruments these activity sources (per its README):

- `Microsoft.Agents.AI`, `Experimental.Microsoft.Agents.AI` (MAF agent spans)
- `Azure.AI.OpenAI*`, `OpenAI.*`, `Experimental.Microsoft.Extensions.AI`
- HTTP client / ASP.NET Core / Azure SDK / SQL client
- Resource detection (Azure App Service, VM, Container Apps)

The only manual flag you still need is the OpenAI experimental switch
(`AppContext.SetSwitch("OpenAI.Experimental.EnableOpenTelemetry", true)`)
because that switch lives in the OpenAI SDK itself, not in the OTel distro.

## Run locally

```pwsh
$env:AZURE_OPENAI_API_KEY = "<your foundry key>"
dotnet run --project .
```

`cloud_RoleName` is `WeatherChatMAF-MS-Distro` so this run can be
filtered out from the original `WeatherChatMAF` data side by side.
