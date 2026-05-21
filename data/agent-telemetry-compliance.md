# Agent Telemetry & SemConv Compliance Matrix

Compliance of the four sample weather agents (LangChain Python, LangChain NodeJs, MAF Python, MAF .NET) with the [OpenTelemetry GenAI semantic conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/) when run against Azure OpenAI Chat Completions API (CAPI) and Foundry Responses API (RAPI) endpoints, using the Microsoft OpenTelemetry distro.

## Score

🟢 **7** · 🟡 **1** · 🔴 **3**

## Span-existence summary

| Span type | Missing on |
|---|---|
| `chat` | Row 11 (MAF .NET Responses) |
| `invoke_agent` | Rows 4, 5, 6 (all LangChain NodeJs) |
| `execute_tool` | none |
| `HTTP` (actual API POST) | Rows 4, 5, 6 (LangChain NodeJs — no HTTP instrumentation) |

## Full matrix

| # | Distro | Client class | Endpoint | Status | execute_tool | invoke_agent | chat | HTTP | Missing / incorrect attributes |
|:-:|---|---|---|:-:|:-:|:-:|:-:|:-:|---|
| 1 | LangChain Python | `AzureChatOpenAI` | Azure CAPI | 🟢 | OK | OK | OK | OK | **chat:** `gen_ai.provider.name` 🔴 non-spec `"azure"`; `gen_ai.request.choice.count` 🟡 Missing<br>**invoke_agent:** `gen_ai.provider.name` 🔴 non-spec `"azure"`; `gen_ai.agent.name`/`id`/`description` 🟠 Missing; `gen_ai.conversation.id` 🟠 Missing |
| 2 | LangChain Python | `ChatOpenAI` | Foundry CAPI | 🟢 | OK | OK | OK | OK | **chat:** `gen_ai.request.choice.count` 🟡 Missing<br>**invoke_agent:** `gen_ai.agent.name`/`id`/`description` 🟠 Missing; `gen_ai.conversation.id` 🟠 Missing |
| 3 | LangChain Python | `ChatOpenAI` (`useResponsesApi`) | Foundry RAPI | 🟡 | OK | OK | OK | OK | **chat:** `gen_ai.usage.input_tokens` 🟡 Missing; `gen_ai.usage.output_tokens` 🟡 Missing; `gen_ai.request.choice.count` 🟡 Missing<br>**invoke_agent:** `gen_ai.agent.name`/`id`/`description` 🟠 Missing; `gen_ai.conversation.id` 🟠 Missing |
| 4 | LangChain NodeJs | `AzureChatOpenAI` | Azure CAPI | 🔴 | OK | **Missing** | OK | **Missing** | **chat:** `gen_ai.provider.name` 🔴 split `"azure"`/`"openai"` (dual instrumentation); `gen_ai.response.id` 🟡 Missing; `gen_ai.response.model` 🟡 Missing; `gen_ai.response.finish_reasons` 🟡 Missing; `gen_ai.request.choice.count` 🟡 Missing<br>**invoke_agent:** 🔴 span entirely absent<br>**execute_tool:** `gen_ai.tool.description` 🟡 Missing |
| 5 | LangChain NodeJs | `ChatOpenAI` | Foundry CAPI | 🔴 | OK | **Missing** | OK | **Missing** | **chat:** `gen_ai.response.id` 🟡 Missing; `gen_ai.response.model` 🟡 Missing; `gen_ai.response.finish_reasons` 🟡 Missing; `gen_ai.request.choice.count` 🟡 Missing<br>**invoke_agent:** 🔴 span entirely absent<br>**execute_tool:** `gen_ai.tool.description` 🟡 Missing |
| 6 | LangChain NodeJs | `ChatOpenAI` (`useResponsesApi`) | Foundry RAPI | 🔴 | OK | **Missing** | OK | **Missing** | **chat:** `gen_ai.response.id` 🟡 Missing; `gen_ai.response.model` 🟡 Missing; `gen_ai.response.finish_reasons` 🟡 Missing; `gen_ai.request.choice.count` 🟡 Missing<br>**invoke_agent:** 🔴 span entirely absent<br>**execute_tool:** `gen_ai.tool.description` 🟡 Missing |
| 7 | MAF Python | `FoundryChatClient` | Foundry RAPI | 🟢 | OK | OK | OK | OK | **chat:** `gen_ai.provider.name` 🔴 non-spec `"azure.ai.foundry"` (Required → `azure.ai.inference`); `gen_ai.response.finish_reasons` 🟡 Missing; `gen_ai.conversation.id` 🟠 partial<br>**invoke_agent:** `gen_ai.provider.name` 🔴 non-spec `"microsoft.agent_framework"`; `gen_ai.agent.description` 🟡 Missing; `gen_ai.conversation.id` 🟠 Missing |
| 8 | MAF Python | `OpenAIChatClient` | Foundry RAPI (responses) | 🟢 | OK | OK | OK | OK | **chat:** `gen_ai.response.finish_reasons` 🟡 Missing; `gen_ai.conversation.id` 🟠 partial<br>**invoke_agent:** `gen_ai.provider.name` 🔴 non-spec `"microsoft.agent_framework"`; `gen_ai.agent.description` 🟡 Missing; `gen_ai.conversation.id` 🟠 Missing |
| 9 | MAF Python | `OpenAIChatCompletionClient` | Azure CAPI | 🟢 | OK | OK | OK | OK | **chat:** `gen_ai.conversation.id` 🟠 Missing _(no other row-specific gaps)_<br>**invoke_agent:** `gen_ai.provider.name` 🔴 non-spec `"microsoft.agent_framework"`; `gen_ai.agent.description` 🟡 Missing; `gen_ai.conversation.id` 🟠 Missing |
| 10 | MAF .NET | `AzureOpenAIClient.GetChatClient` | Azure CAPI | 🟢 (caveat) | OK | OK | OK | OK | **chat:** `gen_ai.provider.name` 🔴 Missing — emits only deprecated `gen_ai.system="openai"`; `gen_ai.request.choice.count` 🟡 Missing; `gen_ai.conversation.id` 🟠 Missing<br>**invoke_agent:** all Required ✓; `gen_ai.conversation.id` 🟠 Missing; `gen_ai.agent.version` 🟡 Missing |
| 11 | MAF .NET | `OpenAIClient.GetResponsesClient` | Foundry RAPI | 🔴 | OK | OK | **Missing** | OK | **chat:** 🔴 span entirely absent for Responses-API code path<br>**invoke_agent:** all Required ✓; `gen_ai.conversation.id` 🟠 Missing; `gen_ai.agent.version` 🟡 Missing |

**Severity legend:** 🔴 Required · 🟠 Conditionally Required · 🟡 Recommended

## Universal gaps (apply to every chat span)

These attributes are absent from **every chat span** in every row. The per-row column above lists only **row-specific** gaps beyond this set.

🟡 Recommended (all rows):
- `server.address`
- `gen_ai.request.temperature`
- `gen_ai.request.max_tokens`
- `gen_ai.request.top_p`
- `gen_ai.request.frequency_penalty`
- `gen_ai.request.presence_penalty`
- `gen_ai.request.stop_sequences`
- `gen_ai.usage.reasoning.output_tokens` (expected on reasoning models `o4-mini`, `DeepSeek-R1`)

Note: Conditional attrs `server.port`, `gen_ai.request.stream`, `gen_ai.output.type` are correctly omitted because their conditions (server.address set / streaming / non-text output) are not met in these scenarios.

## Notable observations

- **LangChain NodeJs has zero HTTP client spans** across all 3 rows — the OpenTelemetry NodeJS distro is not auto-instrumenting outgoing HTTP for the `openai` JS SDK.
- **LangChain NodeJs emits no `invoke_agent` spans** — the JS LangChain instrumentation has no agent-span support yet.
- **Row 4** (LC Node Azure CAPI) has split-provider instrumentation: half the chat spans tag `gen_ai.provider.name="azure"` (LangChain instrumentor) and half `"openai"` (OpenAI SDK instrumentor). Different trace IDs, so not strict same-call dups, but parallel competing instrumentations.
- **Row 7** (MAF Py FoundryChatClient) was previously missing the actual API POST in HTTP spans (only IMDS token GETs were captured). This was fixed by upgrading `agent-framework-foundry` from `1.2.2` to **`1.5.0`**. The Azure-Core pipeline now emits the `POST .../openai/v1/responses` span correctly.
- **Row 9** (MAF Py Azure CAPI) is the only chat span with **no row-specific Required/Recommended gaps** beyond the universal set. A prior duplicate-span regression on this row was fixed by upgrading `microsoft-opentelemetry` from `1.1.0` to **`1.2.0`** (which suppresses a duplicate registration of `opentelemetry-instrumentation-openai-v2`).
- **Row 10** (MAF .NET Azure CAPI) emits the *deprecated* `gen_ai.system="openai"` attribute instead of the renamed Required `gen_ai.provider.name`. The Azure.AI.OpenAI .NET SDK has not yet migrated to the new attribute name.
- **Row 11** (MAF .NET Responses) emits no chat span at all on the Responses-API code path. The `OpenAI.Experimental.EnableOpenTelemetry` AppContext switch only wires Activity emission for the `ChatClient`, not the experimental `ResponsesClient`. Only the raw `POST .../openai/v1/responses` HTTP span (with no `gen_ai.*` attributes) is emitted.
- **`gen_ai.request.choice.count`** is emitted only by MAF Python (30/30 chat spans). All other distros miss it (0/89).
- **`gen_ai.agent.description`** is emitted only by MAF .NET (11/11 invoke_agent spans). Python frameworks miss it on every invoke_agent span.
- **`gen_ai.agent.version`** and **`gen_ai.conversation.id`** are missing on every single invoke_agent span (43/43) across all 4 distros.
- **Provider-name capitalization**: MAF Python invoke_agent spans emit lowercase `"microsoft.agent_framework"` (not `"Microsoft.agent_framework"`).

## Patterns of (non-)compliance

| Pattern | Affected rows |
|---|---|
| `gen_ai.provider.name` Required-but-wrong-value | 1 (`"azure"`), 4 (split), 7 (`"azure.ai.foundry"`) |
| `gen_ai.provider.name` Required-but-missing | 10 (uses deprecated `gen_ai.system` instead) |
| Required span entirely absent | 4–6 (invoke_agent), 11 (chat) |
| `gen_ai.usage.{input,output}_tokens` missing on chat | 3 |
| `gen_ai.response.{id,model,finish_reasons}` missing on chat | 4, 5, 6 |
| `gen_ai.request.choice.count` missing on chat | 1–6, 10 |
| `gen_ai.conversation.id` missing on invoke_agent | all (1–11) |
| `gen_ai.agent.description` missing on invoke_agent | 1–9 |
| HTTP client spans missing | 4–6 |

## Test methodology

Each agent runs against the same Azure Foundry / Azure OpenAI deployments and emits telemetry through the Microsoft OpenTelemetry distro to a single Application Insights resource. Custom dimensions `test.runId`, `test.agent`, and `test.protocol` tag every span for KQL filtering.

### Tested package versions

| Distro | Package | Version |
|---|---|---|
| LangChain Python | `microsoft-opentelemetry` | `1.2.0` |
| LangChain NodeJs | `@microsoft/opentelemetry` | `1.0.2` |
| MAF Python | `microsoft-opentelemetry` | `1.2.0` |
| MAF Python | `agent-framework`, `agent-framework-foundry`, `agent-framework-openai` | `1.5.0` |
| MAF .NET | `Microsoft.OpenTelemetry` | `1.0.2` |

### Reference run IDs (App Insights)

| Distro | runId |
|---|---|
| LangChain Python | `sc2-lcpy-121003` |
| LangChain NodeJs | `sc2-lcnode-120757` |
| MAF Python (rows 8, 9 + row 7 chat attrs) | `sc2-mafpy-120757` |
| MAF Python (row 7 HTTP — post-`agent-framework-foundry` 1.5.0) | `row7-mafpy-foundry-140129` |
| MAF .NET | `sc2-mafnet-120757` |

## Multi-agent topology (Main Agent attribution gap)

The single-agent matrix above tests the flat `agent + tool` pattern. To exercise the multi-agent attribution gap described in the [Main Agent spec](https://microsoft-my.sharepoint.com/:w:/p/zakima/cQokbnuPBNRCRploN7uylRnYEgUCEK5qWgdznH2MfKtu_uA0DQ), all four agents were also refactored to a **3-agent topology** that combines:

1. **Agent-as-tool nesting** — `MainAgent` orchestrates a child `WeatherDataAgent` via a tool that wraps the inner agent (`weather_data_agent`). The inner agent has the raw `get_current_weather` function.
2. **Sequential workflow siblings** — `MainAgent` and `VerifierAgent` run as siblings in a sequential workflow; the verifier sanity-checks the main agent's response.

Expected topology:

```
workflow root
├── MainAgent (invoke_agent)
│   ├── chat
│   ├── execute_tool weather_data_agent     ← agent-as-tool boundary
│   │   └── WeatherDataAgent (invoke_agent) ← nested correctly
│   │       ├── chat
│   │       └── execute_tool get_current_weather (×N cities)
│   └── chat (synthesize)
└── VerifierAgent (invoke_agent)            ← SIBLING
    └── chat
```

### Per-framework attribution findings

| Distro | Main + Verifier sibling parent | WeatherData (agent-as-tool) parent | Main Agent attribution gap reproduced? |
|---|---|---|---|
| MAF Python | ✓ `executor.process` under `workflow.run` (workflow root) | ✓ `execute_tool weather_data_agent` (under Main) | **No** — siblings correctly attributed to the workflow root via `executor.process` parents. |
| MAF .NET | ❌ **No parent — siblings are root spans** | ✓ `execute_tool weather_data_agent` (under Main) | **Yes** — exactly the gap the spec describes. `MainWeatherAgent` and `VerifierAgent` `invoke_agent` spans have no shared parent and no `microsoft.gen_ai.main_agent.*` attribute to bridge them. |
| LangChain Python | ⚠ Parents are LangGraph node spans (`main`, `verify`) which descend from a common `invoke_agent LangGraph` root | ✓ Inner `invoke_agent LangGraph` nested under `tools` span (which is under the data agent's own `invoke_agent LangGraph`) | **Partial** — there *is* a common root, but all 6 `invoke_agent` spans share the generic name `"LangGraph"` (`gen_ai.agent.name` not differentiated per agent), so it is impossible to tell from the span which logical agent (Main / WeatherData / Verifier) it represents. |
| LangChain NodeJs | n/a (no `invoke_agent` spans emitted — see rows 4–6) | n/a (no `invoke_agent` spans emitted) | **Worse** — no `invoke_agent` spans at all; the verifier and main agent are visually indistinguishable in the trace. |

### Multi-agent reference run IDs

| Distro | runId |
|---|---|
| MAF Python (3 protocols) | `ma-mafpy-103656` |
| MAF .NET (2 protocols) | `ma-mafnet-104647` |
| LangChain Python (3 protocols) | `ma-lcpy-105053` |
| LangChain NodeJs (3 protocols, local run — no telemetry export) | `ma-lcnode-105341` |

### Notes

- **MAF Python is the gold standard for multi-agent attribution.** The `agent-framework` workflow runtime emits an outer `workflow.run` span, plus `executor.process <name>` spans per agent step, plus `invoke_agent <AgentName>` under each executor. Sibling agents are unambiguously joined to the workflow.
- **MAF .NET reproduces the spec's attribution gap.** `AgentWorkflowBuilder.BuildSequential` + `InProcessExecution.RunStreamingAsync` invoke each agent but emit **no workflow / executor parent span**. Each agent's `invoke_agent` span is parentless. Without a `microsoft.gen_ai.main_agent.*` attribute (or a synthetic workflow root from the OTel SDK), there is no way to know that `MainWeatherAgent` and `VerifierAgent` belong to the same workflow run.
- **LangChain Python's instrumentation under-names agents.** Every `invoke_agent` span emits `gen_ai.agent.name = "LangGraph"` regardless of which logical agent ran. The trace hierarchy is intact (so sibling attribution works), but the spans are not human-readable without inspecting tool calls in the surrounding spans.
- **LangChain NodeJs emits no `invoke_agent` spans at all** (consistent with rows 4–6 above), so the multi-agent topology is invisible end-to-end — both the agent-as-tool boundary and the sibling workflow are unobservable.

### KQL query — chat spans missing `gen_ai.usage.*`

```kql
dependencies
| where customDimensions.['gen_ai.operation.name'] == 'chat'
| extend inputTokens = tostring(customDimensions.['gen_ai.usage.input_tokens'])
| extend outputTokens = tostring(customDimensions.['gen_ai.usage.output_tokens'])
| where inputTokens == '' or outputTokens == ''
| project timestamp,
          runId = tostring(customDimensions.['test.runId']),
          protocol = tostring(customDimensions.['test.protocol']),
          name, inputTokens, outputTokens
```

### KQL query — per-protocol provider.name on chat spans

```kql
dependencies
| extend opName = tostring(customDimensions.['gen_ai.operation.name'])
| where opName == 'chat'
| extend runId = tostring(customDimensions.['test.runId'])
| extend protocol = tostring(customDimensions.['test.protocol'])
| extend providerName = tostring(customDimensions.['gen_ai.provider.name'])
| summarize count() by runId, protocol, providerName
| order by runId, protocol
```
