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

DEPLOYMENT = "deployment-gpt-5.4-mini"

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
def _make_azure_chat(deployment: str, api_key: str) -> AzureChatOpenAI:
    return AzureChatOpenAI(
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        azure_deployment=deployment,
        model=deployment,
        api_version=AZURE_OPENAI_API_VERSION,
        api_key=api_key,
        timeout=60,
        max_retries=1,
    )


def _make_foundry_chat(deployment: str, api_key: str) -> ChatOpenAI:
    return ChatOpenAI(
        model=deployment,
        base_url=BASE_URL,
        api_key=api_key,
        timeout=60,
        max_retries=1,
        default_headers={"api-key": api_key},
    )


def _make_foundry_responses_chat(deployment: str, api_key: str) -> ChatOpenAI:
    return ChatOpenAI(
        model=deployment,
        base_url=BASE_URL,
        api_key=api_key,
        timeout=60,
        max_retries=1,
        default_headers={"api-key": api_key},
        use_responses_api=True,
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
def build_workflow(chat_model, protocol_tag: str):
    # Inner data agent: has the raw weather tool
    data_agent = create_agent(
        chat_model,
        tools=[get_current_weather],
        system_prompt=DATA_INSTRUCTIONS,
    )

    @tool
    async def weather_data_agent(
        cities: Annotated[str, "Semicolon- or comma-separated list of cities to look up"],
        config: RunnableConfig = None,
    ) -> str:
        """Delegate weather lookups to the weather data agent."""
        result = await data_agent.ainvoke(
            {"messages": [HumanMessage(content=f"Look up weather for: {cities}")]},
            config=config,
        )
        msgs = result.get("messages", [])
        for msg in reversed(msgs):
            if isinstance(msg, AIMessage):
                text = _extract_text(msg)
                if text:
                    return text
        return ""

    # Main agent: has the data-agent-as-tool
    main_agent = create_agent(
        chat_model,
        tools=[weather_data_agent],
        system_prompt=MAIN_INSTRUCTIONS,
    )

    # Verifier agent: no tools
    verifier_agent = create_agent(
        chat_model,
        tools=[],
        system_prompt=VERIFIER_INSTRUCTIONS,
    )

    # Sequential workflow: main -> verifier
    async def main_node(state: MessagesState, config: RunnableConfig):
        before = len(state["messages"])
        result = await main_agent.ainvoke({"messages": state["messages"]}, config=config)
        new_msgs = result["messages"][before:]
        return {"messages": new_msgs}

    async def verify_node(state: MessagesState, config: RunnableConfig):
        before = len(state["messages"])
        result = await verifier_agent.ainvoke({"messages": state["messages"]}, config=config)
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

    try:
        chat_az = _make_azure_chat(DEPLOYMENT, api_key)
        workflows.append(("completions", build_workflow(chat_az, "completions")))
    except Exception as ex:
        print(f"[build] failed completions: {ex}")

    try:
        chat_f = _make_foundry_chat(DEPLOYMENT, api_key)
        workflows.append(("foundry-completions", build_workflow(chat_f, "foundry-completions")))
    except Exception as ex:
        print(f"[build] failed foundry-completions: {ex}")

    try:
        chat_fr = _make_foundry_responses_chat(DEPLOYMENT, api_key)
        workflows.append(("foundry-responses", build_workflow(chat_fr, "foundry-responses")))
    except Exception as ex:
        print(f"[build] failed foundry-responses: {ex}")

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
            result = await graph.ainvoke({"messages": [HumanMessage(content=USER_PROMPT)]})
            return (protocol, result, None)
        except Exception as ex:
            return (protocol, None, ex)

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
