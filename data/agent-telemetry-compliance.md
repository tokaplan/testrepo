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

🟢 **7** · 🟡 **4** · 🔴 **0**

## Streaming coverage

Every implementation now exercises **both** streaming and non-streaming sub-agents inside a single workflow, so the matrix covers the SSE / streaming code path side-by-side with the regular request/response code path:

| Distro | Streaming sub-agent(s) | Non-streaming sub-agent(s) | Mechanism |
|---|---|---|---|
| MAF .NET | Main, Verifier | Data | Main+Verifier via `InProcessExecution.RunStreamingAsync`; Data invoked from Main as a tool via `AsAIFunction → RunAsync` (non-stream) |
| MAF Python | Data | Main, Verifier | `workflow.run(prompt)` (non-stream) → `AgentExecutor` calls Main/Verifier with `stream=False`; Data (wrapped via `Agent.as_tool()`) is forced to stream because `_agent_wrapper` hardcodes `stream=True` |
| LangChain Python | Verifier | Main, Data | Per-role chat clients: Verifier built with `AzureChatOpenAI(streaming=True)`; Main+Data built with default (non-stream) |
| LangChain NodeJs | Verifier | Main, Data | Multi-agent topology (matches LC Python): per-role `@langchain/openai` chat clients; Verifier built with `streaming: true`, Main+Data with default. All three sub-agents wrapped with `createReactAgent({ name, description })` (Verifier with `tools: []`) so each emits its own `invoke_agent` span for parity with the other 3 canonical agents. |

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
| `chat` | _(none)_ — row 6's chat-span gap under `useResponsesApi` closed in `@microsoft/opentelemetry 1.1.0` |
| `invoke_agent` | _(none)_ — row 6's invoke_agent gap closed in `@microsoft/opentelemetry 1.1.0` |
| `execute_tool` | _(none)_ — row 6's intermittent loss closed in `@microsoft/opentelemetry 1.1.0` |
| `HTTP` (actual API POST) | Rows 4, 5, 6 (LangChain NodeJs — no HTTP instrumentation) |

## Full matrix

| # | Distro | Client class | Endpoint | Status | execute_tool | invoke_agent | chat | HTTP | Missing / incorrect attributes |
|:-:|---|---|---|:-:|:-:|:-:|:-:|:-:|---|
| 1 | LangChain Python | `AzureChatOpenAI` | Azure CAPI | 🟢 | OK | OK | OK | OK | **chat:** `gen_ai.provider.name` 🔴 non-spec `"azure"`<br>**invoke_agent:** `gen_ai.provider.name` 🔴 non-spec `"azure"`; `gen_ai.conversation.id` 🟠 Missing |
| 2 | LangChain Python | `ChatOpenAI` | Foundry CAPI | 🟢 | OK | OK | OK | OK | **chat:** _(no row-specific gaps beyond the universal set)_<br>**invoke_agent:** `gen_ai.conversation.id` 🟠 Missing |
| 3 | LangChain Python | `ChatOpenAI` (`useResponsesApi`) | Foundry RAPI | 🟡 | OK | OK | OK | OK | **chat:** `gen_ai.response.model` 🟡 reports deployment alias (e.g. `deployment-gpt-5.4-mini`) instead of the served model snapshot (e.g. `gpt-5.4-mini-2026-03-17`) — Foundry returns the snapshot only in the `x-ms-served-model` response header, and `openai-python` does not surface it to the consumer<br>**invoke_agent:** `gen_ai.conversation.id` 🟠 Missing |
| 4 | LangChain NodeJs | `AzureChatOpenAI` | Azure CAPI | 🟡 | OK | OK | OK | **Missing** | **chat:** `gen_ai.provider.name` 🔴 non-spec `"azure"`; `gen_ai.response.finish_reasons` 🟡 Missing; `gen_ai.request.choice.count` 🟡 Missing<br>**invoke_agent:** `gen_ai.agent.id`/`description` 🟠 Missing; `gen_ai.conversation.id` 🟠 Missing<br>**execute_tool:** `gen_ai.tool.description` 🟡 Missing<br>**trace topology:** 🟠 **Fragmented** — the outer compiled `StateGraph`'s `invoke_agent LangGraph` wrapper span is **not emitted on this row** (it IS emitted on rows 5/6), so `MainWeatherAgent` and `VerifierAgent` siblings have no common parent and each becomes its own trace root (2 separate `operation_Id`s per workflow run). Correlated with the `AzureChatOpenAI` client class specifically — the `@traceloop/instrumentation-langchain` hook on the compiled-graph `invoke` does not fire on this code path. |
| 5 | LangChain NodeJs | `ChatOpenAI` | Foundry CAPI | 🟡 | OK | OK | OK | **Missing** | **chat:** `gen_ai.response.finish_reasons` 🟡 Missing; `gen_ai.request.choice.count` 🟡 Missing<br>**invoke_agent:** `gen_ai.agent.id`/`description` 🟠 Missing; `gen_ai.conversation.id` 🟠 Missing<br>**execute_tool:** `gen_ai.tool.description` 🟡 Missing |
| 6 | LangChain NodeJs | `ChatOpenAI` (`useResponsesApi`) | Foundry RAPI | 🟡 | OK | OK | OK | **Missing** | **chat:** `gen_ai.response.model` 🟡 reports deployment alias (e.g. `deployment-gpt-5.4-mini`) instead of the served model snapshot — Foundry RAPI returns the snapshot only via the `x-ms-served-model` response header, which the `openai` JS SDK does not surface (same as row 3); `gen_ai.response.finish_reasons` 🟡 Missing; `gen_ai.request.choice.count` 🟡 Missing<br>**invoke_agent:** `gen_ai.agent.id`/`description` 🟠 Missing; `gen_ai.conversation.id` 🟠 Missing<br>**execute_tool:** `gen_ai.tool.description` 🟡 Missing |
| 7 | MAF Python | `FoundryChatClient` | Foundry RAPI | 🟢 | OK | OK | OK | OK | **chat:** `gen_ai.provider.name` 🔴 non-spec `"azure.ai.foundry"` (Required → `azure.ai.inference`); `gen_ai.response.finish_reasons` 🟡 Missing; `gen_ai.conversation.id` 🟠 partial<br>**invoke_agent:** `gen_ai.provider.name` 🔴 non-spec `"microsoft.agent_framework"`; `gen_ai.conversation.id` 🟠 Missing |
| 8 | MAF Python | `OpenAIChatClient` | Foundry RAPI (responses) | 🟢 | OK | OK | OK | OK | **chat:** `gen_ai.response.finish_reasons` 🟡 Missing; `gen_ai.conversation.id` 🟠 partial<br>**invoke_agent:** `gen_ai.provider.name` 🔴 non-spec `"microsoft.agent_framework"`; `gen_ai.conversation.id` 🟠 Missing |
| 9 | MAF Python | `OpenAIChatCompletionClient` | Azure CAPI | 🟢 | OK | OK | OK | OK | **chat:** `gen_ai.conversation.id` 🟠 Missing _(no other row-specific gaps)_<br>**invoke_agent:** `gen_ai.provider.name` 🔴 non-spec `"microsoft.agent_framework"`; `gen_ai.conversation.id` 🟠 Missing |
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
- **Row 4 trace fragmentation (LC NodeJs + `AzureChatOpenAI`).** On the `completions` protocol, the outer compiled `StateGraph`'s `invoke_agent LangGraph` wrapper span is never emitted, while it IS emitted on rows 5 and 6 (same StateGraph topology, only difference: chat client class is `ChatOpenAI` on rows 5/6 vs. `AzureChatOpenAI` on row 4). Without the wrapper as a common parent, `MainWeatherAgent` and `VerifierAgent` siblings each become trace roots in **separate `operation_Id`s** (Main+Data in one trace, Verifier in another) — App Insights' End-to-end transaction view will show two disconnected trees per workflow run. Reproduced on `verifagent-lcnode-154632` (row 4 → 2 traces; rows 5/6 → 1 trace each). Likely root cause: the `@traceloop/instrumentation-langchain` hook on the compiled-graph `invoke` does not fire on the `AzureChatOpenAI` code path. Worth reporting upstream.
- **`@microsoft/opentelemetry` 1.1.0 closed several LC NodeJs gaps** (vs. 1.0.2): `chat` spans now emit `gen_ai.response.id` and `gen_ai.response.model` (rows 4–6); row 4's split `gen_ai.provider.name` (`"azure"`/`"openai"` dual instrumentation) is gone — chat spans single-emit with `"azure"`; row 6's `useResponsesApi: true` path now emits `chat` (5/5), `invoke_agent` (3/3), and `execute_tool` (3/3) reliably (was Partial/Missing); `microsoft.gen_ai.main_agent.*` attribution is now implemented (28/29 spans across all 3 protocols carry the main-agent identity).
- **Row 7** (MAF Py FoundryChatClient) was previously missing the actual API POST in HTTP spans (only IMDS token GETs were captured). This was fixed by upgrading `agent-framework-foundry` from `1.2.2` to **`1.5.0`**. The Azure-Core pipeline now emits the `POST .../openai/v1/responses` span correctly.
- **Row 9** (MAF Py Azure CAPI) is the only chat span with **no row-specific Required/Recommended gaps** beyond the universal set. A prior duplicate-span regression on this row was fixed by upgrading `microsoft-opentelemetry` from `1.1.0` to **`1.2.0`** (which suppresses a duplicate registration of `opentelemetry-instrumentation-openai-v2`).
- **Row 10** (MAF .NET Azure CAPI) used to emit the deprecated `gen_ai.system="openai"` attribute instead of the renamed Required `gen_ai.provider.name`. **Fixed in commit `d5cae2e`** by registering the custom `ActivitySource` with the TracerProvider and removing the `OpenAI.Experimental.EnableOpenTelemetry` AppContext switch — `Microsoft.Extensions.AI.OpenTelemetryChatClient` now emits the spans with the new `gen_ai.provider.name="openai"`.
- **Row 11** (MAF .NET Responses) used to emit no chat span at all on the Responses-API code path. **Fixed in commit `d5cae2e`** — `Microsoft.Extensions.AI.OpenTelemetryChatClient` instruments both the Chat Completions and Responses API code paths, and registering the custom `ActivitySource` made every previously-dropped chat span (streaming + non-streaming, completions + responses) visible. Remaining minor gap: `gen_ai.response.finish_reasons` is empty on streaming chat spans (M.E.AI streaming TraceResponse does not surface the finish reason yet).
- **`gen_ai.request.choice.count`** is emitted by MAF Python (30/30 chat spans) and LangChain Python (15/15 chat spans across rows 1–3, after `langchain` 1.x and `microsoft-opentelemetry` 1.3.0). LangChain NodeJs and MAF .NET still omit it.
- **`gen_ai.agent.{name,id,description}`** are now emitted on `invoke_agent` spans by all 3 Python rows (1–3) and MAF .NET (10–11) after both Python agents construct each agent with explicit `name=` / `description=` (and, for LC Py, inject `agent_id` / `agent_description` per-invoke via `RunnableConfig.metadata` — see "LangGraph metadata-wipe note" below). LangChain NodeJs (rows 4–6) now emits `gen_ai.agent.name` on inner Main/Data `invoke_agent` spans (set via `createReactAgent({ name })`); the outer LangGraph `StateGraph` wrapper still emits as `gen_ai.agent.name="LangGraph"`. `gen_ai.agent.id` and `gen_ai.agent.description` remain missing on NodeJs because `RunnableConfig.metadata` propagation to the JS distro tracer isn't wired yet.
- **`gen_ai.agent.version`** and **`gen_ai.conversation.id`** are missing on every single invoke_agent span (43/43) across all 4 distros.
- **Provider-name capitalization**: MAF Python invoke_agent spans emit lowercase `"microsoft.agent_framework"` (not `"Microsoft.agent_framework"`).

## Patterns of (non-)compliance

| Pattern | Affected rows |
|---|---|
| `gen_ai.provider.name` Required-but-wrong-value | 1 (`"azure"`), 4 (`"azure"`), 7 (`"azure.ai.foundry"`) |
| Required span entirely absent | _(none)_ |
| `gen_ai.response.finish_reasons` missing on chat | 4, 5, 6 |
| `gen_ai.response.model` missing on streaming chat only | 10 |
| `gen_ai.response.finish_reasons` missing on streaming chat only | 11 |
| `gen_ai.response.model` reports deployment alias on Foundry RAPI | 3, 6 |
| `gen_ai.request.choice.count` missing on chat | 4, 5, 6, 10, 11 |
| `gen_ai.conversation.id` missing on invoke_agent | all (1–11) |
| `gen_ai.agent.{id,description}` missing on invoke_agent | 4, 5, 6 |
| HTTP client spans missing | 4–6 |

## Test methodology

Each agent runs against the same Azure Foundry / Azure OpenAI deployments and emits telemetry through the Microsoft OpenTelemetry distro to a single Application Insights resource. Custom dimensions `test.runId`, `test.agent`, and `test.protocol` tag every span for KQL filtering.

### Tested package versions

| Distro | Package | Version |
|---|---|---|
| LangChain Python | `microsoft-opentelemetry` | `1.3.0` |
| LangChain Python | `langchain`, `langchain-core`, `langchain-openai` | `1.3.2`, `1.4.0`, `1.2.2` |
| LangChain NodeJs | `@microsoft/opentelemetry` | `1.1.0` |
| MAF Python | `microsoft-opentelemetry` | `1.3.0` |
| MAF Python | `agent-framework`, `agent-framework-core`, `agent-framework-foundry`, `agent-framework-openai` | `1.6.0` |
| MAF .NET | `Microsoft.Agents.AI`, `Microsoft.Agents.AI.OpenAI`, `Microsoft.Agents.AI.Workflows` | `1.7.0` |
| MAF .NET | `Microsoft.Extensions.AI.OpenAI` | `10.6.0` |
| MAF .NET | `Microsoft.OpenTelemetry` | `1.0.3` |

### Reproducibility note: `SEQUENTIAL=1` for the Python agents

The MAF Python and LangChain Python `main.py` scripts default to running the per-protocol workflows in parallel via `asyncio.gather`. Under parallel execution, both the langchain instrumentor and `agent_framework`'s span processor non-deterministically drop chat / `invoke_agent` / `execute_tool` spans (the workflows themselves still succeed). **All matrix validation runs must be executed with `SEQUENTIAL=1` set** so each protocol's workflow runs to completion before the next starts — this captures the full span set. The LangChain NodeJs `main.js` also supports `SEQUENTIAL=1` for the same reason. The MAF .NET program is single-protocol-per-run by construction and needs no knob.

### Reproducibility note: Application Insights ingestion timing

Application Insights typically ingests telemetry within **~15 seconds** of the agent emitting it. When validating a run:

1. After the agent exits, wait **15 seconds** before issuing the first KQL query for `customDimensions['test.runId'] == '<runId>'`.
2. If the expected spans are not yet visible, re-query every **15 seconds** until they appear.
3. Treat anything longer than ~2 minutes as an ingestion stall and investigate (network, connection string, BatchSpanProcessor flush, etc.) rather than waiting indefinitely.

Do not poll faster than every 15 seconds — it just wastes calls; the backing pipeline does not flush per-query.

### LangGraph metadata-wipe note (LangChain Python only)

The Microsoft OTEL distro's LangChain instrumentor reads `gen_ai.agent.id` and `gen_ai.agent.description` from each chain run's `extra.metadata` keys `agent_id` / `agent_description`, and `gen_ai.agent.name` from `lc_agent_name` (set automatically by `create_agent(name=...)`).

The natural construction-time API for binding metadata to a Runnable is `Runnable.with_config(metadata={...})`. **In LangGraph that binding is wiped when dispatching to a nested compiled subgraph** — each subgraph node rebuilds its `RunnableConfig` from a LangGraph-internal set of keys (`langgraph_step`, `langgraph_node`, `langgraph_path`, ...), so any user-bound metadata never reaches the per-agent `Run`. As a result, `with_config(metadata=...)` alone leaves `gen_ai.agent.id` / `gen_ai.agent.description` empty even though the same code works for a direct top-level `.ainvoke()`.

The basic-user workaround is to pass metadata at **invoke time** instead of at construction time — `await agent.ainvoke(state, config={"metadata": {"agent_id": ..., "agent_description": ...}})` — in each graph node and each `@tool`-wrapped agent-as-tool delegate. Per-invoke metadata survives the LangGraph dispatch and reaches the run that the distro instruments. The agent-as-tool wrapper must **override** the parent's metadata (rather than merge it in unchanged) so that nested agent runs carry their own role's id/description, not the calling agent's.

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
| LangChain NodeJs | ✓ Both `MainWeatherAgent-<proto>` and `VerifierAgent-<proto>` emit named `invoke_agent` spans (Verifier now wrapped with `createReactAgent({ tools: [] })`). Same caveat as below — they share a generic `invoke_agent LangGraph` outer parent on the `foundry-*` protocols. | ✓ Inner `invoke_agent <WeatherDataAgent-...>` nested under `execute_tool weather_data_agent` (which is under the named Main `invoke_agent`) | **Partial** — multi-agent nesting works and all 3 sub-agents (Main / Data / Verifier) are individually named, but the outer `StateGraph` compiled wrapper still emits a generic `invoke_agent LangGraph` parent above the named Main/Verifier inner agents (no way to differentiate the workflow root from a logical agent via `gen_ai.agent.name` alone). |

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
- **LangChain NodeJs (Microsoft distro)** emits `invoke_agent` spans via the LangChain instrumentor included with `@microsoft/opentelemetry 1.1.0`. All three sub-agents (Main, Data, Verifier) are wrapped with `createReactAgent({ name })` so each emits its own named `invoke_agent` span (e.g. `invoke_agent MainWeatherAgent-completions`, `invoke_agent VerifierAgent-completions`, `invoke_agent WeatherDataAgent-completions`) — full parity with the sibling 3-agent flows in LC Python, MAF Python, and MAF .NET. The outer compiled `StateGraph` still emits a generic `invoke_agent LangGraph` wrapper on the `foundry-*` protocols. `microsoft.gen_ai.main_agent.*` propagation **is now implemented** in `1.1.0` (was not in `1.0.2`) and tags 28/29 spans across a 3-protocol run with the outermost agent's identity.

## Main Agent attribution spec compliance

Microsoft has published a spec for how the Azure Monitor distros (Python, .NET, Java, Node.js) should propagate **main-agent identity** through every span (and log) emitted during a multi-agent run: [`genai_main_agent_attribution.md`](https://github.com/aep-health-and-standards/Telemetry-Collection-Spec/blob/main/ApplicationInsights/genai_main_agent_attribution.md).

In short, the distro MUST register a SpanProcessor whose:

- **OnStart** copies the parent span's `microsoft.gen_ai.main_agent.{name,id,version,conversation_id}` onto the child (or falls back to the parent's `gen_ai.agent.{name,id,version}` / `gen_ai.conversation.id`).
- **OnEnd** self-promotes the span's `gen_ai.agent.*` to `microsoft.gen_ai.main_agent.*` if (a) the span is `gen_ai.operation.name = invoke_agent` and (b) the span doesn't already have any `microsoft.gen_ai.main_agent.*`.

End-state: every span in a trace is tagged with the **outermost agent** of its branch so customers can group telemetry by main agent.

### Per-distro compliance (multi-agent runs above)

| Distro | Distro package | OnStart inheritance (children) | OnEnd self-promotion (root `invoke_agent`) | All 4 spec attributes emitted? | Verdict |
|---|---|:-:|:-:|:-:|---|
| MAF Python | `microsoft-opentelemetry 1.3.0` | ✅ works — `chat` 12/12 (100%) and `execute_tool` 9/9 (100%) inherit `main_agent.{name,id}` from parent's `gen_ai.agent.*` (up from 82% / 67% on `1.2.0`) | ❌ root Main + Verifier `invoke_agent` spans still never get `main_agent.*` (only 3/8 invoke_agent spans attributed — the nested `WeatherDataAgent` siblings, via OnStart from a chat/tool parent) | ⚠ partial — `name` + `id` present on all child spans, `version` 0/all, `conversation_id` partial | **Partial — improved** — `1.3.0` closed the child-inheritance gap (chat / execute_tool now 100%); the root `invoke_agent` OnEnd self-promotion is still not implemented. |
| MAF .NET | `Microsoft.OpenTelemetry 1.0.3` + `Microsoft.Agents.AI 1.7.0` | ✅ works — all chat / execute_tool / HTTP / nested `invoke_agent` spans inherit | ✅ works — root `MainWeatherAgent` and `VerifierAgent` `invoke_agent` spans self-promote `gen_ai.agent.name → microsoft.gen_ai.main_agent.name` | ⚠ partial — `name` + `id` present on **100%** of spans (16/16 chat-completions run, 23/23 responses run); `version` 0/all (no `gen_ai.agent.version` to fall back from); `conversation_id` partial | ✅ **Fully compliant for `name` + `id`** — newly implemented in `1.0.3`. Was "Not implemented" in `1.0.2`. |
| LangChain Python | `microsoft-opentelemetry 1.3.0` | ❌ no children attributed | ❌ no roots attributed | ❌ none | **Broken upstream — unchanged on `1.3.0`** — the distro's SpanProcessor *is* registered (same package as MAF Py) but the LangChain `invoke_agent LangGraph` spans have **no** `gen_ai.agent.name` attribute at all in customDimensions, so OnStart has nothing to copy and OnEnd has nothing to promote. The fix has to land in the LangChain instrumentor, not in `microsoft-opentelemetry`. |
| LangChain NodeJs | `@microsoft/opentelemetry 1.1.0` | ✅ works — chat / execute_tool / nested `invoke_agent` all inherit `main_agent.name` from the parent invoke_agent's `gen_ai.agent.name` (28/29 spans across the 3-protocol `distro11c-lcnode-152908` run; the single miss is a Verifier chat whose parent `invoke_agent LangGraph` wasn't emitted under one protocol) | ✅ works — root `invoke_agent` spans self-promote `gen_ai.agent.name → microsoft.gen_ai.main_agent.name` | ⚠ partial — `name` present on ~96%, `id`/`description` not set (no source attribute to promote); `conversation_id` not set | ✅ **Newly implemented in `1.1.0`** — was "Not implemented" in `1.0.2`. |

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

### Evidence (MAF Python coverage by span kind — `1.2.0` vs `1.3.0`)

Comparing `v2-mafpy-112454` (distro `1.2.0`) against `v3-mafpy-150803` (distro `1.3.0`, same workflow, same 3 protocols):

| Span kind | `1.2.0` w/ `main_agent.name` | `1.3.0` w/ `main_agent.name` | Δ |
|---|---:|---:|---|
| `chat`        | 9 / 11 (82%) | **12 / 12 (100%)** | ✅ inheritance fixed |
| `execute_tool`| 6 / 9 (67%)  | **9 / 9 (100%)**   | ✅ inheritance fixed |
| `invoke_agent`| 1 / 5 (20%)  | 3 / 8 (37%)        | ❌ root OnEnd still broken — the attributed `invoke_agent` spans are nested `WeatherDataAgent`s that inherited from their parent execute_tool / chat; root `MainWeatherAgent` and `VerifierAgent` `invoke_agent` spans still lack `main_agent.*` |

### Evidence (sample span breakdown — MAF Python, `responses` protocol, `ma-mafpy-103656`)

MAF Python's per-span behavior on `1.3.0` is the same shape as before (children inherit, roots still miss the OnEnd self-promotion):

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
- ✅ With **MAF Python (`microsoft-opentelemetry 1.3.0`)**, customers can now filter or aggregate **100% of `chat` / `execute_tool` / HTTP / nested `invoke_agent`** spans by `microsoft.gen_ai.main_agent.name` (up from ~70-80% on `1.2.0`). `1.3.0` closed the OnStart inheritance gap for children.
- ❌ With **MAF Python**, the two **root `invoke_agent`** spans per workflow run (Main + Verifier) are still NOT included in such a filter — the OnEnd self-promotion gap is still present in `microsoft-opentelemetry 1.3.0`. Workarounds: filter on `gen_ai.agent.name` for those rows, or wait for an OnEnd fix in the Python distro.
- ❌ With **LangChain Python**, the spec is registered but not effective — no spans get `microsoft.gen_ai.main_agent.*` because the upstream LangChain instrumentor emits no `gen_ai.agent.name` at all. Upgrading the distro from `1.2.0` to `1.3.0` did **not** change this (verified via runs `v2-lcpy-112454` and `v5-lcpy-150231`). Customers must rely on parent-span traversal in KQL to scope a query.
- ✅ With **LangChain NodeJs** (`@microsoft/opentelemetry 1.1.0`), customers can now filter or aggregate ~96% of spans in a multi-agent trace by `microsoft.gen_ai.main_agent.name`. The OnStart / OnEnd SpanProcessor is newly implemented in `1.1.0` (was "Not implemented" in `1.0.2`). `id`, `version`, and `conversation_id` remain unattributed because the upstream `gen_ai.agent.*` source attributes are not emitted by the LangChain JS instrumentor for these fields.

### Reference runs (latest, after Python distro upgrade to `1.3.0`)

| Distro | runId | Distro package(s) |
|---|---|---|
| MAF Python | `v3-mafpy-150803` | `microsoft-opentelemetry 1.3.0`, `agent-framework 1.6.0` |
| MAF .NET | `v4-mafnet-130929` | `Microsoft.OpenTelemetry 1.0.3`, `Microsoft.Agents.AI 1.7.0`, `Microsoft.Agents.AI.Workflows 1.7.0` |
| LangChain Python | `v5-lcpy-150231` | `microsoft-opentelemetry 1.3.0`, `langchain 1.2.16`, `langgraph 1.1.10` |
| LangChain NodeJs | `verifagent-lcnode-154632` | `@microsoft/opentelemetry 1.1.0`, `@langchain/langgraph 0.4.0` |

Earlier baselines for comparison: `v2-mafpy-112454` (MAF Py on `1.2.0`), `v2-lcpy-112454` (LC Py on `1.2.0`).

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
