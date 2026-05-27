# Canonical agent implementations

> **This file is the single source of truth for which agent implementations
> participate in the telemetry / semconv compliance matrix
> (`data/agent-telemetry-compliance.md`).**
>
> All validation runs, all matrix rows, all "the 4 agents" statements, and all
> session checkpoints refer to **exactly** the four implementations listed
> below. Any other folder in this repository is legacy/scratch and **must not
> be touched** when validating the matrix.

## The 4 canonical implementations (MS OTEL distro)

All four use the **Microsoft OpenTelemetry distro** (`Azure.Monitor.OpenTelemetry.AspNetCore`
for .NET, `azure-monitor-opentelemetry` for Python, `@azure/monitor-opentelemetry`
for Node.js) and emit telemetry to the same Application Insights resource.

| # | Implementation | Disk path | Entry point | Project file |
|:-:|---|---|---|---|
| 1 | **MAF .NET** | `MAF with Microsoft OTEL distro\DotNet\` | `Program.cs` | `WeatherChatMAF.MSDistro.csproj` |
| 2 | **MAF Python** | `MAF with Microsoft OTEL distro\Python\` | `main.py` | `pyproject.toml` / `requirements.txt` |
| 3 | **LangChain Python** | `LangChain with Microsoft OTEL distro\Python\` | `main.py` | `pyproject.toml` / `requirements.txt` |
| 4 | **LangChain NodeJs** | `LangChain with Microsoft OTEL distro\NodeJs\` | `main.js` | `package.json` |

Each implementation runs against the same backend resources, drives the same
prompt and weather tool, and emits the same `test.agent`, `test.runId`,
`test.protocol` span attributes so that runs are correlatable in Application
Insights.

### Shared resources

| Resource | Value |
|---|---|
| Foundry endpoint | `https://alkap-mc9jji6o-eastus2.services.ai.azure.com/api/projects/alkap-mc9jji6o-eastus2_project` |
| Azure OpenAI endpoint | `https://alkap-mc9jji6o-eastus2.cognitiveservices.azure.com` |
| Application Insights | `data-1` in resource group `alkaplan-longchain` |
| Cloud-role names | `WeatherChatMAF-MS-Distro`, `WeatherChatMAFPython-MS-Distro`, `WeatherChatLangChain-MS-Distro`, `WeatherChatLangChainNodeJs-MS-Distro` |

### Protocol coverage (the 11 matrix rows)

Each of the 4 canonical agents exercises 2–3 protocol variants in a single
run. That's how 4 implementations produce 11 matrix rows:

| Row(s) | Implementation | Protocol(s) |
|:-:|---|---|
| 1, 2, 3 | LangChain Python | Azure CAPI, Foundry CAPI, Foundry RAPI |
| 4, 5, 6 | LangChain NodeJs | Azure CAPI, Foundry CAPI, Foundry RAPI |
| 7, 8, 9 | MAF Python | Foundry RAPI (FoundryChatClient), Foundry RAPI (OpenAIChatClient), Azure CAPI |
| 10, 11 | MAF .NET | Azure CAPI, Foundry RAPI |

## Legacy folders — DO NOT USE for matrix validation

The following top-level folders predate the MS-distro work and have been
**superseded**. They emit different telemetry (different cloud-role names,
different SDK versions, possibly different topology) and **must not** be used
when reporting on or refreshing the compliance matrix:

- `LangChainNodeJs\` (superseded by `LangChain with Microsoft OTEL distro\NodeJs\`)
- `LangChainPython\` (superseded by `LangChain with Microsoft OTEL distro\Python\`)
- `WeatherChat\` (early WeatherChat baseline)
- `WeatherChatMAF\` (superseded by `MAF with Microsoft OTEL distro\DotNet\`)
- `WeatherChatMAFPython\` (superseded by `MAF with Microsoft OTEL distro\Python\`)
- `WeatherChatPython\` (superseded by `LangChain with Microsoft OTEL distro\Python\`)
- `TeamsAgent\` (unrelated Teams project)

## Pre-flight checklist for any validation run

Before kicking off a new compliance / telemetry validation run, mentally
confirm:

1. **Path** — the `cd` / `Set-Location` target is one of the four canonical
   paths above (rooted at `MAF with Microsoft OTEL distro\…` or
   `LangChain with Microsoft OTEL distro\…`).
2. **Cloud-role name** — once telemetry arrives, the KQL filter is on the
   matching `cloud_RoleName` value above. If the role name doesn't match, the
   wrong implementation was run.
3. **Backend** — the Foundry / Azure OpenAI endpoints and the `data-1`
   Application Insights resource are the canonical shared resources.
4. **Run-ID convention** — pass an explicit `test.runId` (e.g.
   `verify-mafnet-<HHmmss>`) so the run is queryable end-to-end.

If any of these is wrong, **stop and re-check** — the result will not be
comparable to existing matrix rows.
