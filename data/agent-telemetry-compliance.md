# Agent Telemetry & SemConv Compliance Matrix

Compliance of the four sample weather agents (LangChain Python, LangChain NodeJs, MAF Python, MAF .NET) with the [OpenTelemetry GenAI semantic conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/) when run against Azure OpenAI Chat Completions API (CAPI) and Foundry Responses API (RAPI) endpoints, using the Microsoft OpenTelemetry distro.

> ## 📌 Scope — the 4 canonical implementations
>
> **Every row of this matrix is produced by exactly one of these four
> folders. Do not substitute, do not validate against legacy folders. See
> [`../CANONICAL-AGENTS.md`](../CANONICAL-AGENTS.md) for the full pre-flight
> checklist.**
>
> | # | Implementation | Disk path | Entry point |
> |:-:|---|---|---|
> | 1 | **MAF .NET** | `MAF with Microsoft OTEL distro\DotNet\` | `Program.cs` |
> | 2 | **MAF Python** | `MAF with Microsoft OTEL distro\Python\` | `main.py` |
> | 3 | **LangChain Python** | `LangChain with Microsoft OTEL distro\Python\` | `main.py` |
> | 4 | **LangChain NodeJs** | `LangChain with Microsoft OTEL distro\NodeJs\` | `main.js` |
>
> Row → implementation mapping: rows **1, 2, 3** = LangChain Python · rows **4, 5, 6** = LangChain NodeJs · rows **7, 8, 9** = MAF Python · rows **10, 11** = MAF .NET.
>
> Legacy folders (e.g. `WeatherChat\`, `WeatherChatMAF\`, `LangChainPython\`,
> `LangChainNodeJs\`) are **superseded** and must not be used for matrix
> validation.

## Score

🟢 **7** · 🟡 **3** · 🔴 **1**

## Streaming coverage

Every implementation now exercises **both** streaming and non-streaming sub-agents inside a single workflow, so the matrix covers the SSE / streaming code path side-by-side with the regular request/response code path:

| Distro | Streaming sub-agent(s) | Non-streaming sub-agent(s) | Mechanism |
|---|---|---|---|
| MAF .NET | Main, Verifier | Data | Main+Verifier via `InProcessExecution.RunStreamingAsync`; Data invoked from Main as a tool via `AsAIFunction → RunAsync` (non-stream) |
| MAF Python | Data | Main, Verifier | `workflow.run(prompt)` (non-stream) → `AgentExecutor` calls Main/Verifier with `stream=False`; Data (wrapped via `Agent.as_tool()`) is forced to stream because `_agent_wrapper` hardcodes `stream=True` |
| LangChain Python | Verifier | Main, Data | Per-role chat clients: Verifier built with `AzureChatOpenAI(streaming=True)`; Main+Data built with default (non-stream) |
| LangChain NodeJs | Verifier | Main, Data | Multi-agent topology (matches LC Python): per-role `@langchain/openai` chat clients; Verifier with `streaming: true`, Main+Data with default |

Mixed-mode verified by HTTP-call monkey-patching the OpenAI SDK / `fetch` on each implementation:

| Distro | Probe run | Calls per workflow | stream=true | stream=false |
|---|---|---|---|---|
| MAF .NET | telemetry (`mix-mafnet-215259`) — chat span `gen_ai.request.stream` attr | 5 per protocol | 3 (Main planning + Main synthesis + Verifier) | 2 (Data ×2) |
| MAF Python | `probe_mafpy_stream.py` (completions protocol) | 5 | 2 (Data ×2 via `as_tool`) | 3 (Main planning, Main synthesis, Verifier) |
| LangChain Python | `probe_lcpy_stream.py` (per-role factories) | 5 per protocol | 1 (Verifier) | 4 (Main ×2 + Data ×2) |
| LangChain NodeJs | `probe_lcnode_stream.mjs` (all 3 protocols) | 5 per protocol | 1 (Verifier) | 4 (Main ×2 + Data ×2) |

Only MAF .NET surfaces a `gen_ai.request.stream=true` (and `gen_ai.response.time_to_first_chunk`) attribute on its chat spans. The Python `agent_framework` chat instrumentation and the LangChain Python/NodeJs instrumentations do not emit a streaming flag at all (the underlying SDK call is invoked with `stream=True`, verified by the probes above, but the attribute is omitted on the span). This is the same "universal gap" listed in the gaps section below.

## Span-existence summary

| Span type | Missing on |
|---|---|
| `chat` | Row 6 (LangChain NodeJs `useResponsesApi`) — only the Verifier (direct `chat.invoke`) emits a chat span; sub-agent calls made through `createReactAgent` produce no chat spans when the underlying client uses `useResponsesApi: true` |
| `invoke_agent` | Row 6 only (Rows 4, 5 gained `invoke_agent` via multi-agent refactor — see commit `29be769`) |
| `execute_tool` | Row 6 (intermittent — `weather_data_agent` tool span is sometimes lost under `useResponsesApi`) |
| `HTTP` (actual API POST) | Rows 4, 5, 6 (LangChain NodeJs — no HTTP instrumentation) |

## Full matrix

| # | Distro | Client class | Endpoint | Status | execute_tool | invoke_agent | chat | HTTP | Missing / incorrect attributes |
|:-:|---|---|---|:-:|:-:|:-:|:-:|:-:|---|
| 1 | LangChain Python | `AzureChatOpenAI` | Azure CAPI | 🟢 | OK | OK | OK | OK | **chat:** `gen_ai.provider.name` 🔴 non-spec `"azure"`; `gen_ai.request.choice.count` 🟡 Missing<br>**invoke_agent:** `gen_ai.provider.name` 🔴 non-spec `"azure"`; `gen_ai.agent.name`/`id`/`description` 🟠 Missing; `gen_ai.conversation.id` 🟠 Missing |
| 2 | LangChain Python | `ChatOpenAI` | Foundry CAPI | 🟢 | OK | OK | OK | OK | **chat:** `gen_ai.request.choice.count` 🟡 Missing<br>**invoke_agent:** `gen_ai.agent.name`/`id`/`description` 🟠 Missing; `gen_ai.conversation.id` 🟠 Missing |
| 3 | LangChain Python | `ChatOpenAI` (`useResponsesApi`) | Foundry RAPI | 🟡 | OK | OK | OK | OK | **chat:** `gen_ai.response.model` 🟡 reports deployment alias (e.g. `deployment-gpt-5.4-mini`) instead of the served model snapshot (e.g. `gpt-5.4-mini-2026-03-17`) — Foundry returns the snapshot only in the `x-ms-served-model` response header, and `openai-python` does not surface it to the consumer; `gen_ai.usage.input_tokens` 🟡 Missing; `gen_ai.usage.output_tokens` 🟡 Missing; `gen_ai.request.choice.count` 🟡 Missing<br>**invoke_agent:** `gen_ai.agent.name`/`id`/`description` 🟠 Missing; `gen_ai.conversation.id` 🟠 Missing |
| 4 | LangChain NodeJs | `AzureChatOpenAI` | Azure CAPI | 🟡 | OK | OK | OK | **Missing** | **chat:** `gen_ai.provider.name` 🔴 split `"azure"`/`"openai"` (dual instrumentation); `gen_ai.request.model` 🟡 reports default `"gpt-3.5-turbo"` instead of deployment name (Azure SDK omits `model` from body, so OTel falls back to the SDK default); `gen_ai.response.id` 🟡 Missing; `gen_ai.response.model` 🟡 Missing; `gen_ai.response.finish_reasons` 🟡 Missing; `gen_ai.request.choice.count` 🟡 Missing<br>**invoke_agent:** ✅ now emitted via `createReactAgent` after the multi-agent refactor (`29be769`); `gen_ai.agent.name`/`id`/`description` 🟠 Missing; `gen_ai.conversation.id` 🟠 Missing<br>**execute_tool:** `gen_ai.tool.description` 🟡 Missing |
| 5 | LangChain NodeJs | `ChatOpenAI` | Foundry CAPI | 🟡 | OK | OK | OK | **Missing** | **chat:** `gen_ai.response.id` 🟡 Missing; `gen_ai.response.model` 🟡 Missing; `gen_ai.response.finish_reasons` 🟡 Missing; `gen_ai.request.choice.count` 🟡 Missing<br>**invoke_agent:** ✅ now emitted via `createReactAgent` after the multi-agent refactor (`29be769`); `gen_ai.agent.name`/`id`/`description` 🟠 Missing; `gen_ai.conversation.id` 🟠 Missing<br>**execute_tool:** `gen_ai.tool.description` 🟡 Missing |
| 6 | LangChain NodeJs | `ChatOpenAI` (`useResponsesApi`) | Foundry RAPI | 🔴 | **Partial** | **Missing** | **Partial** | **Missing** | **chat:** 🔴 only the Verifier (direct `chat.invoke`) emits a chat span; the 4 sub-agent calls inside `createReactAgent` (Main planning, Main synthesis, Data ×2) produce no chat spans at all when `useResponsesApi: true` — LangChain JS instrumentation does not hook the Responses-API path inside `createReactAgent`. Same `gen_ai.response.*` / `choice.count` gaps as rows 4/5.<br>**invoke_agent:** 🔴 span entirely absent (Responses-API + `createReactAgent` combination)<br>**execute_tool:** `weather_data_agent` tool span intermittently lost; `get_current_weather` never emitted (inner data agent's tool call is silent); `gen_ai.tool.description` 🟡 Missing |
| 7 | MAF Python | `FoundryChatClient` | Foundry RAPI | 🟢 | OK | OK | OK | OK | **chat:** `gen_ai.provider.name` 🔴 non-spec `"azure.ai.foundry"` (Required → `azure.ai.inference`); `gen_ai.response.finish_reasons` 🟡 Missing; `gen_ai.conversation.id` 🟠 partial<br>**invoke_agent:** `gen_ai.provider.name` 🔴 non-spec `"microsoft.agent_framework"`; `gen_ai.agent.description` 🟡 Missing; `gen_ai.conversation.id` 🟠 Missing |
| 8 | MAF Python | `OpenAIChatClient` | Foundry RAPI (responses) | 🟢 | OK | OK | OK | OK | **chat:** `gen_ai.response.finish_reasons` 🟡 Missing; `gen_ai.conversation.id` 🟠 partial<br>**invoke_agent:** `gen_ai.provider.name` 🔴 non-spec `"microsoft.agent_framework"`; `gen_ai.agent.description` 🟡 Missing; `gen_ai.conversation.id` 🟠 Missing |
| 9 | MAF Python | `OpenAIChatCompletionClient` | Azure CAPI | 🟢 | OK | OK | OK | OK | **chat:** `gen_ai.conversation.id` 🟠 Missing _(no other row-specific gaps)_<br>**invoke_agent:** `gen_ai.provider.name` 🔴 non-spec `"microsoft.agent_framework"`; `gen_ai.agent.description` 🟡 Missing; `gen_ai.conversation.id` 🟠 Missing |
| 10 | MAF .NET | `AzureOpenAIClient.GetChatClient` | Azure CAPI | 🟢 | OK | OK | OK | OK | **chat:** `gen_ai.response.model` 🟡 Missing on streaming spans only (M.E.AI streaming TraceResponse gap — same gap also affects the streaming `invoke_agent` aggregate); `gen_ai.request.choice.count` 🟡 Missing; `gen_ai.conversation.id` 🟠 Missing<br>**invoke_agent:** `gen_ai.response.model` 🟡 Missing on streaming agent invocations (Main, Verifier); populated on non-streaming (Data); `gen_ai.conversation.id` 🟠 Missing; `gen_ai.agent.version` 🟡 Missing |
| 11 | MAF .NET | `AIProjectClient` (`FoundryChatClient` via `AsAIAgent`) | Foundry RAPI | 🟢 | OK | OK | OK | OK | **chat:** `gen_ai.provider.name` 🔴 non-spec `"microsoft.foundry"` (Required → `azure.ai.openai`); `gen_ai.response.finish_reasons` 🟡 Missing on non-streaming chat spans (populated on streaming); `gen_ai.request.choice.count` 🟡 Missing; `gen_ai.conversation.id` 🟠 partial (set on follow-up Responses-API turns via `previous_response_id`, absent on the first turn)<br>**invoke_agent:** `gen_ai.provider.name` 🔴 non-spec `"microsoft.foundry"`; `gen_ai.response.finish_reasons` 🟡 Missing on non-streaming agent invocations (populated on streaming); `gen_ai.conversation.id` 🟠 Missing; `gen_ai.agent.version` 🟡 Missing<br>**Note:** Wired through `Microsoft.Agents.AI.Foundry` 1.7.0-preview.260526.1's `AIProjectClient.AsAIAgent(...)` which constructs `FoundryChatClient`. That client registers `ServedModelPolicy` (PR microsoft/agent-framework#5979, shipped in 1.6.2-preview+) to capture the `x-ms-served-model` Azure OpenAI response header and overwrite `ChatResponse.ModelId` with the underlying snapshot (e.g. `gpt-4o-mini-2024-07-18`) instead of the deployment alias. Previously this row used `OpenAIClient.GetResponsesClient().AsIChatClient()` which bypassed the policy entirely and emitted the alias in `gen_ai.response.model`. |

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

Note: `gen_ai.usage.reasoning.output_tokens` is omitted from this list — the active model rotation contains only chat models (no reasoning models like `o4-mini` / `DeepSeek-R1`), so the attribute is correctly absent.

Note: Conditional attrs `server.port` and `gen_ai.output.type` are correctly omitted because their conditions (server.address set / non-text output) are not met in these scenarios. **`gen_ai.request.stream`** is now exercised on every implementation (see Streaming coverage section above), but only MAF .NET's instrumentation emits the attribute on chat spans; MAF Python's `agent_framework` and the LangChain Python/NodeJs MS-distro instrumentations omit it even when the underlying HTTP call uses `stream=true`.

## Notable observations

- **LangChain NodeJs has zero HTTP client spans** across all 3 rows — the OpenTelemetry NodeJS distro is not auto-instrumenting outgoing HTTP for the `openai` JS SDK.
- **LangChain NodeJs emits no `invoke_agent` spans** — the JS LangChain instrumentation has no agent-span support yet.
- **Row 4** (LC Node Azure CAPI) has split-provider instrumentation: half the chat spans tag `gen_ai.provider.name="azure"` (LangChain instrumentor) and half `"openai"` (OpenAI SDK instrumentor). Different trace IDs, so not strict same-call dups, but parallel competing instrumentations.
- **Row 7** (MAF Py FoundryChatClient) was previously missing the actual API POST in HTTP spans (only IMDS token GETs were captured). This was fixed by upgrading `agent-framework-foundry` from `1.2.2` to **`1.5.0`**. The Azure-Core pipeline now emits the `POST .../openai/v1/responses` span correctly.
- **Row 9** (MAF Py Azure CAPI) is the only chat span with **no row-specific Required/Recommended gaps** beyond the universal set. A prior duplicate-span regression on this row was fixed by upgrading `microsoft-opentelemetry` from `1.1.0` to **`1.2.0`** (which suppresses a duplicate registration of `opentelemetry-instrumentation-openai-v2`).
- **Row 10** (MAF .NET Azure CAPI) used to emit the deprecated `gen_ai.system="openai"` attribute instead of the renamed Required `gen_ai.provider.name`. **Fixed in commit `d5cae2e`** by registering the custom `ActivitySource` with the TracerProvider and removing the `OpenAI.Experimental.EnableOpenTelemetry` AppContext switch — `Microsoft.Extensions.AI.OpenTelemetryChatClient` now emits the spans with the new `gen_ai.provider.name="openai"`.
- **Row 11** (MAF .NET Responses) used to emit no chat span at all on the Responses-API code path. **Fixed in commit `d5cae2e`** — `Microsoft.Extensions.AI.OpenTelemetryChatClient` instruments both the Chat Completions and Responses API code paths, and registering the custom `ActivitySource` made every previously-dropped chat span (streaming + non-streaming, completions + responses) visible. Remaining minor gap: `gen_ai.response.finish_reasons` is empty on streaming chat spans (M.E.AI streaming TraceResponse does not surface the finish reason yet).
- **`gen_ai.request.choice.count`** is emitted only by MAF Python (30/30 chat spans). All other distros miss it (0/89).
- **`gen_ai.agent.description`** is emitted only by MAF .NET (11/11 invoke_agent spans). Python frameworks miss it on every invoke_agent span.
- **`gen_ai.agent.version`** and **`gen_ai.conversation.id`** are missing on every single invoke_agent span (43/43) across all 4 distros.
- **Provider-name capitalization**: MAF Python invoke_agent spans emit lowercase `"microsoft.agent_framework"` (not `"Microsoft.agent_framework"`).

## Patterns of (non-)compliance

| Pattern | Affected rows |
|---|---|
| `gen_ai.provider.name` Required-but-wrong-value | 1 (`"azure"`), 4 (split), 7 (`"azure.ai.foundry"`) |
| Required span entirely absent | 4–6 (invoke_agent) |
| `gen_ai.usage.{input,output}_tokens` missing on chat | 3 |
| `gen_ai.response.{id,model,finish_reasons}` missing on chat | 4, 5, 6 |
| `gen_ai.response.model` missing on streaming chat only | 10 |
| `gen_ai.response.finish_reasons` missing on streaming chat only | 11 |
| `gen_ai.request.choice.count` missing on chat | 1–6, 10, 11 |
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
| MAF Python | `agent-framework`, `agent-framework-core`, `agent-framework-foundry`, `agent-framework-openai` | `1.6.0` |
| MAF .NET | `Microsoft.Agents.AI`, `Microsoft.Agents.AI.OpenAI`, `Microsoft.Agents.AI.Workflows` | `1.7.0` |
| MAF .NET | `Microsoft.Extensions.AI.OpenAI` | `10.6.0` |
| MAF .NET | `Microsoft.OpenTelemetry` | `1.0.3` |

### Resolved issue: `gen_ai.response.model` on RAPI returned deployment alias

In older runs against the Foundry Responses API (run `sc2-*` from ~2 weeks earlier on
MAF Py `agent-framework 1.2.2` and LC Py `microsoft-opentelemetry 1.2.0`), the chat
span's `gen_ai.response.model` carried the **deployment alias** (e.g.
`"deployment-gpt-5.4-mini"`) instead of the **real versioned model** (e.g.
`"gpt-5.4-mini-2026-03-17"`). CAPI paths were unaffected. The fix landed
server-side in the Foundry Responses API (and was also defensively addressed in MAF
1.6.0 Python / 1.7.0 .NET). Verified in run `rmodel-mafpy-after-175542`: all chat
spans on all three MAF Python protocols (`completions`, `responses`, `RAPI via
foundry`) now carry the real versioned model name.

### Reference run IDs (App Insights)

| Distro | runId |
|---|---|
| LangChain Python | `sc2-lcpy-121003` |
| LangChain NodeJs | `sc2-lcnode-120757` |
| MAF Python (rows 8, 9 + row 7 chat attrs) | `sc2-mafpy-120757` |
| MAF Python (row 7 HTTP — post-`agent-framework-foundry` 1.5.0) | `row7-mafpy-foundry-140129` |
| MAF .NET | `sc2-mafnet-120757` |

### Streaming-coverage reference run IDs

| Distro | runId | Notes |
|---|---|---|
| LangChain Python | `stream-lcpy-205911` | Verifier chat model built with `streaming=True` |
| LangChain NodeJs | `stream-lcnode-210022` | All chat models built with `streaming: true` |
| MAF Python | `stream-mafpy-205811` | Whole workflow runs via `workflow.run(prompt, stream=True)` |
| MAF .NET | `stream-mafnet-210325` | `InProcessExecution.RunStreamingAsync` (Main + Verifier stream) |

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
| MAF .NET | ❌ **No parent — siblings are root spans**, but ✅ now bridged via `microsoft.gen_ai.main_agent.name` attribute (see Main Agent attribution section below) | ✓ `execute_tool weather_data_agent` (under Main) | **Closed in `Microsoft.OpenTelemetry 1.0.3`** — root sibling `invoke_agent` spans still have no shared parent, but the spec's `microsoft.gen_ai.main_agent.*` SpanProcessor now propagates the main-agent identity correctly, so customers *can* group sibling roots and all descendant spans by main agent. |
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
- **MAF .NET reproduces (and then closes) the spec's attribution gap.** `AgentWorkflowBuilder.BuildSequential` + `InProcessExecution.RunStreamingAsync` invoke each agent but emit **no workflow / executor parent span**. Each agent's `invoke_agent` span is parentless. The trace topology alone cannot tell you that `MainWeatherAgent` and `VerifierAgent` belong to the same workflow run — but `Microsoft.OpenTelemetry 1.0.3` now implements the [Main Agent attribution spec](#main-agent-attribution-spec-compliance) (both OnStart inheritance and OnEnd self-promotion), so every span carries `microsoft.gen_ai.main_agent.{name,id}` identifying the outermost agent of its branch. Customers can now group by main agent without traversing the parent chain.
- **LangChain Python's instrumentation under-names agents.** Every `invoke_agent` span emits `gen_ai.agent.name = "LangGraph"` regardless of which logical agent ran. The trace hierarchy is intact (so sibling attribution works), but the spans are not human-readable without inspecting tool calls in the surrounding spans.
- **LangChain NodeJs emits no `invoke_agent` spans at all** (consistent with rows 4–6 above), so the multi-agent topology is invisible end-to-end — both the agent-as-tool boundary and the sibling workflow are unobservable.

## Main Agent attribution spec compliance

Microsoft has published a spec for how the Azure Monitor distros (Python, .NET, Java, Node.js) should propagate **main-agent identity** through every span (and log) emitted during a multi-agent run: [`genai_main_agent_attribution.md`](https://github.com/aep-health-and-standards/Telemetry-Collection-Spec/blob/main/ApplicationInsights/genai_main_agent_attribution.md).

In short, the distro MUST register a SpanProcessor whose:

- **OnStart** copies the parent span's `microsoft.gen_ai.main_agent.{name,id,version,conversation_id}` onto the child (or falls back to the parent's `gen_ai.agent.{name,id,version}` / `gen_ai.conversation.id`).
- **OnEnd** self-promotes the span's `gen_ai.agent.*` to `microsoft.gen_ai.main_agent.*` if (a) the span is `gen_ai.operation.name = invoke_agent` and (b) the span doesn't already have any `microsoft.gen_ai.main_agent.*`.

End-state: every span in a trace is tagged with the **outermost agent** of its branch so customers can group telemetry by main agent.

### Per-distro compliance (multi-agent runs above)

| Distro | Distro package | OnStart inheritance (children) | OnEnd self-promotion (root `invoke_agent`) | All 4 spec attributes emitted? | Verdict |
|---|---|:-:|:-:|:-:|---|
| MAF Python | `microsoft-opentelemetry 1.2.0` | ✅ works (`name`, `id` via `gen_ai.agent.*` fallback) | ❌ root Main + Verifier `invoke_agent` spans never get `main_agent.*` | ⚠ partial — `name` + `id` present on children, `version` 0/all, `conversation_id` partial | **Partial** — children attributed via parent's `gen_ai.agent.name`, but root `invoke_agent` spans are unattributed. *(unchanged from previous validation — distro version unchanged)* |
| MAF .NET | `Microsoft.OpenTelemetry 1.0.3` + `Microsoft.Agents.AI 1.7.0` | ✅ works — all chat / execute_tool / HTTP / nested `invoke_agent` spans inherit | ✅ works — root `MainWeatherAgent` and `VerifierAgent` `invoke_agent` spans self-promote `gen_ai.agent.name → microsoft.gen_ai.main_agent.name` | ⚠ partial — `name` + `id` present on **100%** of spans (16/16 chat-completions run, 23/23 responses run); `version` 0/all (no `gen_ai.agent.version` to fall back from); `conversation_id` partial | ✅ **Fully compliant for `name` + `id`** — newly implemented in `1.0.3`. Was "Not implemented" in `1.0.2`. |
| LangChain Python | `microsoft-opentelemetry 1.2.0` | ❌ no children attributed | ❌ no roots attributed | ❌ none | **Broken upstream** — the distro's SpanProcessor *is* registered (same package as MAF Py) but the LangChain `invoke_agent LangGraph` spans have an empty `gen_ai.agent.name` customDimension, so OnStart has nothing to copy and OnEnd has nothing to promote. |
| LangChain NodeJs | no `@microsoft/opentelemetry` Node package installed (traceloop-based) | n/a — no `invoke_agent` spans emitted at all | n/a | ❌ none | **Not applicable** — no Microsoft Node distro on the agent today; relies on `@traceloop/instrumentation-langchain 0.14.6` which doesn't emit `invoke_agent` spans. |

### Evidence (sample span breakdown — MAF .NET, `responses` protocol, `v2-mafnet-112454`)

This is the new evidence after the `Microsoft.OpenTelemetry 1.0.3` + `Microsoft.Agents.AI 1.7.0` upgrade — the spec is now correctly enforced.

| Span | `gen_ai.agent.name` | `microsoft.gen_ai.main_agent.name` |
|---|---|---|
| `invoke_agent MainWeatherAgent-responses` (root) | `MainWeatherAgent-responses` | `MainWeatherAgent-responses` ← OnEnd self-promoted ✓ |
| `chat deployment-gpt-5.4-mini` (under Main) | — | `MainWeatherAgent-responses` ← OnStart inherited ✓ |
| `execute_tool weather_data_agent` (under Main) | — | `MainWeatherAgent-responses` ← OnStart inherited ✓ |
| `invoke_agent WeatherDataAgent-responses` (nested under Main) | `WeatherDataAgent-responses` | `MainWeatherAgent-responses` ← OnStart inherited from parent ✓ |
| `chat deployment-gpt-4o-mini` (under WeatherData) | — | `MainWeatherAgent-responses` ← OnStart inherited ✓ |
| `invoke_agent VerifierAgent-responses` (sibling root) | `VerifierAgent-responses` | `VerifierAgent-responses` ← OnEnd self-promoted ✓ |
| `chat deployment-gpt-4o` (under Verifier) | — | `VerifierAgent-responses` ← OnStart inherited ✓ |

### Evidence (sample span breakdown — MAF Python, `responses` protocol, `ma-mafpy-103656`)

MAF Python's behavior is **unchanged** from the previous validation — the distro version (`microsoft-opentelemetry 1.2.0`) has not been re-released:

| Span | `gen_ai.agent.name` | `microsoft.gen_ai.main_agent.name` |
|---|---|---|
| `invoke_agent MainWeatherAgent-responses` (root) | `MainWeatherAgent-responses` | **(missing)** ← OnEnd self-promotion bug |
| `chat` (under Main) | — | `MainWeatherAgent-responses` ← OnStart inherited |
| `execute_tool weather_data_agent` (under Main) | — | `MainWeatherAgent-responses` ← OnStart inherited |
| `invoke_agent WeatherDataAgent-responses` (nested) | `WeatherDataAgent-responses` | `MainWeatherAgent-responses` ← OnStart inherited from parent execute_tool's fallback |
| `execute_tool get_current_weather` (under WeatherData) | — | `MainWeatherAgent-responses` ← OnStart inherited |
| `invoke_agent VerifierAgent-responses` (sibling root) | `VerifierAgent-responses` | **(missing)** ← OnEnd self-promotion bug |
| `chat` (under Verifier) | — | `VerifierAgent-responses` ← OnStart inherited |
| `workflow.run`, `executor.process …`, `edge_group.process …`, `message.send` | — | **(missing)** ← correctly skipped (no parent with `gen_ai.agent.*`) |

### What customers can / cannot do today

- ✅ With **MAF .NET (`Microsoft.OpenTelemetry 1.0.3`)**, customers can filter or aggregate **every** span in a multi-agent trace — root `invoke_agent`, nested `invoke_agent`, `chat`, `execute_tool`, HTTP — by `microsoft.gen_ai.main_agent.name` to scope a query to a single top-level agent. The spec is fully effective for `name` and `id`. *(`version` is missing because the underlying `gen_ai.agent.version` source attribute is never emitted; `conversation_id` is partial.)*
- ✅ With **MAF Python**, customers *can* filter or aggregate **chat / execute_tool / HTTP / nested invoke_agent** spans by `microsoft.gen_ai.main_agent.name` to scope a query to a single top-level agent.
- ❌ With **MAF Python**, the two **root `invoke_agent`** spans per workflow run (Main + Verifier) are NOT included in such a filter. This is the OnEnd self-promotion gap, still present in `microsoft-opentelemetry 1.2.0`. Workarounds: filter on `gen_ai.agent.name` for those rows, or wait for an OnEnd fix in the Python distro.
- ❌ With **LangChain Python**, the spec is registered but not effective — no spans get `microsoft.gen_ai.main_agent.*` because the upstream LangChain instrumentor emits empty `gen_ai.agent.name`. Customers must rely on parent-span traversal in KQL to scope a query.
- ❌ With **LangChain NodeJs**, there is no Microsoft Node distro installed; the agent uses `@traceloop/*` instrumentation which emits no `invoke_agent` spans at all.

### Reference runs (v2 validation, after distro upgrade)

| Distro | runId | Distro package(s) |
|---|---|---|
| MAF Python | `v2-mafpy-112454` | `microsoft-opentelemetry 1.2.0`, `agent-framework 1.6.0` |
| MAF .NET | `v2-mafnet-112454` | `Microsoft.OpenTelemetry 1.0.3`, `Microsoft.Agents.AI 1.7.0`, `Microsoft.Agents.AI.Workflows 1.7.0` |
| LangChain Python | `v2-lcpy-112454` | `microsoft-opentelemetry 1.2.0`, `langchain 1.2.16`, `langgraph 1.1.10` |
| LangChain NodeJs | `v2-lcnode-112454` | `@traceloop/instrumentation-langchain 0.14.6` (no Microsoft Node distro) |

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
