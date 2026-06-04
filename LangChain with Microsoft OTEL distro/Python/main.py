"""
LangChainPython with Microsoft OpenTelemetry distro - multi-agent topology
(agent-as-tool + sequential workflow) mirroring the MAF agents.

Topology per protocol:

    StateGraph (sequential workflow)
    +- MainAgent (create_agent, tools=[weather_data_agent_tool])
    |  +- weather_data_agent_tool  <-- @tool wrapping inner data_agent (agent-as-tool)
    |     +- DataAgent (create_agent, tools=[get_current_weather])
    +- VerifierAgent (create_agent, no tools)
"""

from __future__ import annotations

import asyncio
import contextvars
import json
import os
import sys
import uuid
from typing import Annotated

from microsoft.opentelemetry import use_microsoft_opentelemetry
from microsoft.opentelemetry._genai._langchain._tracer_instrumentor import (
    LangChainInstrumentor,
)
from opentelemetry import trace
from opentelemetry.sdk.trace import SpanProcessor as BaseSpanProcessor

from langchain_openai import AzureChatOpenAI, ChatOpenAI
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from langchain_core.runnables import RunnableConfig
from langchain.agents import create_agent
from langgraph.graph import StateGraph, START, END, MessagesState

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
ENDPOINT = "https://alkap-mc9jji6o-eastus2.services.ai.azure.com/api/projects/alkap-mc9jji6o-eastus2_project"
BASE_URL = ENDPOINT + "/openai/v1/"
AZURE_OPENAI_ENDPOINT = "https://alkap-mc9jji6o-eastus2.cognitiveservices.azure.com"
AZURE_OPENAI_API_VERSION = "2025-04-01-preview"

DEPLOYMENT = "deployment-gpt-5.4-mini"  # fallback / unused when AGENT_DEPLOYMENTS is in effect

# Multi-agent topology: assign a different deployment to each agent role so a
# single workflow run produces telemetry from multiple models. Matches the
# MAF agents' per-role deployment scheme.
AGENT_DEPLOYMENTS = {
    "data":     "deployment-gpt-4o-mini",   # tool-caller
    "main":     "deployment-gpt-5.4-mini",  # orchestrator
    "verifier": "deployment-gpt-4o",        # judge (chat model)
}

SERVICE_NAME = "LangChainPython-MS-Distro"
USER_PROMPT = "What's the weather like in Seattle and San Francisco?"

DATA_INSTRUCTIONS = (
    "You are a weather data agent. You look up weather information for "
    "one or more cities using the get_current_weather tool. "
    "Call the tool ONCE per requested city, then return a concise JSON-like "
    "string containing all results. Do not add any commentary."
)

MAIN_INSTRUCTIONS = (
    "You are a friendly weather assistant. When the user asks about weather, "
    "delegate the lookup to the weather_data_agent tool by passing it the list "
    "of cities (e.g. 'Seattle, WA; San Francisco, CA'). Then summarize the "
    "results to the user in plain English."
)

VERIFIER_INSTRUCTIONS = (
    "You are a verifier agent. You will see a conversation between a user and "
    "a weather assistant. Sanity-check the assistant's response. Look for: "
    "(1) hallucinated cities not in the user's question, "
    "(2) impossible temperature/condition pairs, "
    "(3) missing cities the user asked about. "
    "Reply with one line starting with 'VERIFIED: ...' if the response is sound, "
    "or 'WARN: ...' if not. Do not call any tools."
)


# ---------------------------------------------------------------------------
# Test-tagging span processor
# ---------------------------------------------------------------------------
class TestAgentSpanProcessor(BaseSpanProcessor):
    _protocol_ctx: contextvars.ContextVar[str] = contextvars.ContextVar(
        "test_protocol", default=""
    )

    def __init__(self, agent_name: str, run_id: str):
        self._agent_name = agent_name
        self._run_id = run_id

    @classmethod
    def set_protocol(cls, protocol: str) -> None:
        cls._protocol_ctx.set(protocol)

    def on_start(self, span, parent_context=None):
        span.set_attribute("test.agent", self._agent_name)
        span.set_attribute("test.runId", self._run_id)
        protocol = self._protocol_ctx.get("")
        if protocol:
            span.set_attribute("test.protocol", protocol)

    def on_end(self, span):
        pass

    def shutdown(self):
        pass

    def force_flush(self, timeout_millis=None):
        return True


DEFAULT_APP_INSIGHTS_CONNECTION_STRING = (
    "InstrumentationKey=06533fcd-4317-4b63-9c52-a518c492d907;"
    "IngestionEndpoint=https://eastus2-3.in.applicationinsights.azure.com/;"
    "LiveEndpoint=https://eastus2.livediagnostics.monitor.azure.com/;"
    "ApplicationId=66a40307-82d6-4baf-8886-37141dc8d391"
)


# Human-readable descriptions for each agent role. These get attached as
# `gen_ai.agent.description` via the standard LangChain `Runnable.with_config`
# metadata mechanism (see build_workflow below). Mirrors the MAF agents'
# Agent(description=...) constructor kwarg.
DATA_AGENT_DESCRIPTION = "Looks up weather for one or more cities via get_current_weather."
MAIN_AGENT_DESCRIPTION = "Friendly weather assistant that delegates lookups to a data agent."
VERIFIER_AGENT_DESCRIPTION = "Sanity-checks the main agent's weather report."


# ---------------------------------------------------------------------------
# Inner weather tool (raw function)
# ---------------------------------------------------------------------------
WEATHER_DATA = {
    "seattle, wa": (55, "Rainy"),
    "san francisco, ca": (63, "Foggy"),
    "new york, ny": (72, "Sunny"),
}


@tool
def get_current_weather(
    location: Annotated[str, "The city and state, e.g. San Francisco, CA"],
    unit: Annotated[str, "The temperature unit (defaults to fahrenheit)"] = "fahrenheit",
) -> str:
    """Gets the current weather for a given location."""
    temp_f, condition = WEATHER_DATA.get(location.lower(), (68, "Partly cloudy"))
    if unit == "celsius":
        temp = int((temp_f - 32) * 5.0 / 9.0)
        unit_label = "C"
    else:
        temp = temp_f
        unit_label = "F"

    print(f'[Tool] get_current_weather("{location}", "{unit}")')
    return json.dumps(
        {"location": location, "temperature": f"{temp}{unit_label}", "condition": condition}
    )


# ---------------------------------------------------------------------------
# Chat client factories
# ---------------------------------------------------------------------------
def _make_azure_chat(deployment: str, api_key: str, streaming: bool = False) -> AzureChatOpenAI:
    return AzureChatOpenAI(
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        azure_deployment=deployment,
        model=deployment,
        api_version=AZURE_OPENAI_API_VERSION,
        api_key=api_key,
        timeout=60,
        max_retries=1,
        streaming=streaming,
    )


def _make_foundry_chat(deployment: str, api_key: str, streaming: bool = False) -> ChatOpenAI:
    return ChatOpenAI(
        model=deployment,
        base_url=BASE_URL,
        api_key=api_key,
        timeout=60,
        max_retries=1,
        default_headers={"api-key": api_key},
        streaming=streaming,
    )


def _make_foundry_responses_chat(deployment: str, api_key: str, streaming: bool = False) -> ChatOpenAI:
    return ChatOpenAI(
        model=deployment,
        base_url=BASE_URL,
        api_key=api_key,
        timeout=60,
        max_retries=1,
        default_headers={"api-key": api_key},
        use_responses_api=True,
        streaming=streaming,
    )


def _extract_text(message) -> str:
    content = getattr(message, "content", None)
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                txt = block.get("text") or block.get("content")
                if isinstance(txt, str):
                    parts.append(txt)
        return "".join(parts)
    return str(content)


# ---------------------------------------------------------------------------
# Build the multi-agent workflow for a given chat model
# ---------------------------------------------------------------------------
def build_workflow(data_model, main_model, verifier_model, protocol_tag: str):
    # Per-role agent identities. Generated once at workflow construction so
    # each agent has a stable `gen_ai.agent.id` for the lifetime of this run
    # (same pattern as MAF's Agent(), which auto-assigns a UUID per instance).
    data_agent_id = str(uuid.uuid4())
    main_agent_id = str(uuid.uuid4())
    verifier_agent_id = str(uuid.uuid4())

    data_agent_name = f"WeatherDataAgent-{protocol_tag}"
    main_agent_name = f"MainWeatherAgent-{protocol_tag}"
    verifier_agent_name = f"VerifierAgent-{protocol_tag}"

    # Per-agent metadata that the Microsoft OpenTelemetry distro lifts onto
    # `invoke_agent` spans as `gen_ai.agent.id` / `gen_ai.agent.description`.
    # NOTE: We pass this on every .ainvoke() call (per-call RunnableConfig)
    # rather than via `.with_config(metadata=...)` because LangGraph rebuilds
    # the RunnableConfig when dispatching to each subgraph node, which drops
    # any metadata previously bound via with_config. Per-call config metadata
    # survives that round-trip and is the documented LC mechanism for
    # attaching run-level metadata.
    data_meta = {
        "agent_id": data_agent_id,
        "agent_description": DATA_AGENT_DESCRIPTION,
    }
    main_meta = {
        "agent_id": main_agent_id,
        "agent_description": MAIN_AGENT_DESCRIPTION,
    }
    verifier_meta = {
        "agent_id": verifier_agent_id,
        "agent_description": VERIFIER_AGENT_DESCRIPTION,
    }

    # Inner data agent: has the raw weather tool.
    # `name=` is the public create_agent kwarg; the Microsoft distro's
    # LangChain instrumentor lifts it into the `invoke_agent <name>` span
    # name and the `gen_ai.agent.name` attribute.
    data_agent = create_agent(
        data_model,
        tools=[get_current_weather],
        system_prompt=DATA_INSTRUCTIONS,
        name=data_agent_name,
    )

    @tool
    async def weather_data_agent(
        cities: Annotated[str, "Semicolon- or comma-separated list of cities to look up"],
        config: RunnableConfig = None,
    ) -> str:
        """Delegate weather lookups to the weather data agent."""
        # The tool body runs inside main agent's context, so the incoming
        # `config.metadata` already carries main_meta. Override it with
        # data_meta for the nested data agent's run so its invoke_agent span
        # carries the data role's id/description, not main's.
        parent_meta = (config or {}).get("metadata", {}) if config else {}
        nested_config = {
            **(config or {}),
            "metadata": {**parent_meta, **data_meta},
        }
        result = await data_agent.ainvoke(
            {"messages": [HumanMessage(content=f"Look up weather for: {cities}")]},
            config=nested_config,
        )
        msgs = result.get("messages", [])
        for msg in reversed(msgs):
            if isinstance(msg, AIMessage):
                text = _extract_text(msg)
                if text:
                    return text
        return ""

    # Main agent: has the data-agent-as-tool.
    main_agent = create_agent(
        main_model,
        tools=[weather_data_agent],
        system_prompt=MAIN_INSTRUCTIONS,
        name=main_agent_name,
    )

    # Verifier agent: no tools.
    verifier_agent = create_agent(
        verifier_model,
        tools=[],
        system_prompt=VERIFIER_INSTRUCTIONS,
        name=verifier_agent_name,
    )

    # Sequential workflow: main -> verifier.
    # Each node merges per-agent metadata into the per-call RunnableConfig so
    # the Microsoft distro's LangChain instrumentor can lift agent_id /
    # agent_description onto the corresponding `invoke_agent` span.
    async def main_node(state: MessagesState, config: RunnableConfig):
        parent_meta = (config or {}).get("metadata", {}) if config else {}
        cfg = {**(config or {}), "metadata": {**parent_meta, **main_meta}}
        before = len(state["messages"])
        result = await main_agent.ainvoke({"messages": state["messages"]}, config=cfg)
        new_msgs = result["messages"][before:]
        return {"messages": new_msgs}

    async def verify_node(state: MessagesState, config: RunnableConfig):
        parent_meta = (config or {}).get("metadata", {}) if config else {}
        cfg = {**(config or {}), "metadata": {**parent_meta, **verifier_meta}}
        before = len(state["messages"])
        result = await verifier_agent.ainvoke({"messages": state["messages"]}, config=cfg)
        new_msgs = result["messages"][before:]
        return {"messages": new_msgs}

    graph = (
        StateGraph(MessagesState)
        .add_node("main", main_node)
        .add_node("verify", verify_node)
        .add_edge(START, "main")
        .add_edge("main", "verify")
        .add_edge("verify", END)
        .compile(name=f"WeatherWorkflow-{protocol_tag}")
    )

    return graph


def build_workflows(api_key: str):
    workflows = []

    def _factory(protocol):
        if protocol == "completions":
            return lambda d, streaming=False: _make_azure_chat(d, api_key, streaming=streaming)
        if protocol == "foundry-completions":
            return lambda d, streaming=False: _make_foundry_chat(d, api_key, streaming=streaming)
        if protocol == "foundry-responses":
            return lambda d, streaming=False: _make_foundry_responses_chat(d, api_key, streaming=streaming)
        raise ValueError(protocol)

    for protocol in ("completions", "foundry-completions", "foundry-responses"):
        try:
            make = _factory(protocol)
            data_m = make(AGENT_DEPLOYMENTS["data"])
            main_m = make(AGENT_DEPLOYMENTS["main"])
            # Stream the verifier so that at least one agent per workflow exercises
            # the streaming chat-completions / responses-API path. LangChain's
            # `streaming=True` flag makes invoke()/ainvoke() internally consume
            # the HTTP SSE stream while still returning a single AIMessage at the
            # end, which keeps the LangGraph flow unchanged.
            verifier_m = make(AGENT_DEPLOYMENTS["verifier"], streaming=True)
            workflows.append((protocol, build_workflow(data_m, main_m, verifier_m, protocol)))
        except Exception as ex:
            print(f"[build] failed {protocol}: {ex}")

    return workflows


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
async def run_once(workflows, run_label: str) -> int:
    print(f"\n=== Run: {run_label} ===")
    print(f"You: {USER_PROMPT}\n")

    async def _run(protocol, graph):
        TestAgentSpanProcessor.set_protocol(protocol)
        try:
            # One conversation per workflow run. The Microsoft OTEL distro's
            # LangChain instrumentor reads `thread_id` / `conversation_id` /
            # `session_id` from RunnableConfig.metadata and emits it as
            # `gen_ai.conversation.id` on every span. LangGraph propagates
            # metadata down the run tree, so setting it once at the top
            # invocation covers all child runs.
            conversation_id = str(uuid.uuid4())
            result = await graph.ainvoke(
                {"messages": [HumanMessage(content=USER_PROMPT)]},
                config={"metadata": {"thread_id": conversation_id}},
            )
            return (protocol, result, None)
        except Exception as ex:
            return (protocol, None, ex)

    if os.environ.get("SEQUENTIAL", "").lower() in ("1", "true", "yes"):
        results = []
        for p, g in workflows:
            results.append(await _run(p, g))
    else:
        results = await asyncio.gather(*(_run(p, g) for (p, g) in workflows))
    successes = 0
    for protocol, result, error in results:
        print(f"--- [{protocol}] ---")
        if error is not None:
            print(f"  Error: {error}")
            continue
        successes += 1

        # The final state messages are: [user, ...main_agent_msgs, ...verifier_msgs].
        # Walk backwards to grab the verifier's final text and the main's final text.
        msgs = result.get("messages", [])
        ai_texts = []
        for msg in msgs:
            if isinstance(msg, AIMessage):
                text = _extract_text(msg)
                if text and not text.startswith("[tool"):
                    ai_texts.append(text)
        if len(ai_texts) >= 2:
            print(f"  Assistant: {ai_texts[-2]}")
            print(f"  Verifier:  {ai_texts[-1]}")
        elif ai_texts:
            print(f"  (single AI text): {ai_texts[-1]}")
    print(f"\n[{run_label}] {successes}/{len(results)} workflows succeeded")
    return successes


async def main() -> int:
    run_id = sys.argv[1] if len(sys.argv) > 1 else str(uuid.uuid4())
    print(f"Service: {SERVICE_NAME}")
    print(f"RunId:   {run_id}")

    connection_string = os.environ.get(
        "APPLICATIONINSIGHTS_CONNECTION_STRING", DEFAULT_APP_INSIGHTS_CONNECTION_STRING
    )
    print(f"AppInsights: {connection_string[:60]}...")

    os.environ.setdefault("OTEL_SERVICE_NAME", SERVICE_NAME)

    # Pre-install the LangChain instrumentor with our app version so the
    # Microsoft OpenTelemetry distro's auto-install (which runs inside
    # use_microsoft_opentelemetry below) is a no-op for LangChain and
    # our agent_version is preserved.  The distro reads `agent_version`
    # from the instrumentor's _agent_config (init-time, not per-invoke),
    # so this is the documented seam for setting it.  All invoke_agent
    # spans in the process share this single value -- the SDK does not
    # support per-agent versions today.
    LangChainInstrumentor().instrument(agent_version="1.0.0")

    use_microsoft_opentelemetry(
        enable_azure_monitor=True,
        azure_monitor_connection_string=connection_string,
    )

    test_processor = TestAgentSpanProcessor(SERVICE_NAME, run_id)
    trace.get_tracer_provider().add_span_processor(test_processor)

    api_key = os.environ.get("AZURE_OPENAI_API_KEY", "")
    if not api_key:
        print("Error: AZURE_OPENAI_API_KEY is required.")
        return 1

    workflows = build_workflows(api_key)
    print(f"Built {len(workflows)} workflow variants.")

    loop_forever = os.environ.get("LOOP_FOREVER", "").lower() in ("1", "true", "yes")
    interval = int(os.environ.get("LOOP_INTERVAL_SECONDS", "60"))

    iteration = 0
    while True:
        iteration += 1
        await run_once(workflows, f"iteration-{iteration}")
        if not loop_forever:
            break
        print(f"\nSleeping {interval}s before next iteration...")
        await asyncio.sleep(interval)

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
