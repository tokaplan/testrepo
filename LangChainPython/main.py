"""
LangChainPython - LangChain.py port of WeatherChatMAFPython.

All telemetry comes from AKS App Monitoring auto-instrumentation (the Microsoft
Python OTEL distro injected by the `azure-monitor-auto-instrumentation-python`
init container). The only in-code instrumentation kept here is a SpanProcessor
that stamps the same `test.agent` / `test.runId` / `test.protocol` attributes
that WeatherChatMAFPython puts on every span, so the data lines up across runs.

When run locally (no auto-instrumentation), no telemetry is exported. The agent
itself still works.
"""

from __future__ import annotations

import asyncio
import contextvars
import json
import os
import sys
import uuid
from typing import Annotated, Optional

from opentelemetry import trace
from opentelemetry.trace import SpanKind
from opentelemetry.sdk.trace import SpanProcessor as BaseSpanProcessor

from langchain_openai import AzureChatOpenAI, ChatOpenAI
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from langchain.agents import create_agent

# ---------------------------------------------------------------------------
# Configuration - mirrors WeatherChatMAFPython exactly
# ---------------------------------------------------------------------------
ENDPOINT = "https://alkap-mc9jji6o-eastus2.services.ai.azure.com/api/projects/alkap-mc9jji6o-eastus2_project"
BASE_URL = ENDPOINT + "/openai/v1/"
AZURE_OPENAI_ENDPOINT = "https://alkap-mc9jji6o-eastus2.cognitiveservices.azure.com"
AZURE_OPENAI_API_VERSION = "2025-04-01-preview"

DEPLOYMENT_NAMES = [
    "deployment-gpt-5.4-mini",
    "deployment-gpt-4o",
    "deployment-gpt-4o-mini",
    "deployment-o4-mini",
    "deployment-Phi-4",
    "deployment-DeepSeek-R1",
    "deployment-Llama-3.3-70B-Instruct",
]

NO_TOOL_DEPLOYMENTS = {
    "deployment-Phi-4",
    "deployment-DeepSeek-R1",
}

SERVICE_NAME = "LangChainPython"
GENAI_SOURCE_NAME = "LangChainPython.GenAI"
USER_PROMPT = "What's the weather like in Seattle and San Francisco?"


# ---------------------------------------------------------------------------
# Custom-attribute SpanProcessor
# ---------------------------------------------------------------------------
class TestAttributesProcessor(BaseSpanProcessor):
    """Stamps every span with test.agent / test.runId / test.protocol.

    Attached to whatever TracerProvider the AKS auto-instrumentation distro
    has installed as the global provider; if no SDK provider is present (e.g.
    local runs without auto-instrumentation), `add_span_processor` is unavailable
    and the call is silently skipped.
    """

    def __init__(self, agent_name: str, run_id: str):
        self._agent_name = agent_name
        self._run_id = run_id
        self._protocol_ctx: "contextvars.ContextVar[str]" = contextvars.ContextVar(
            "test_protocol", default=""
        )

    def set_protocol(self, protocol: str) -> None:
        self._protocol_ctx.set(protocol)

    def on_start(self, span, parent_context=None):  # type: ignore[override]
        span.set_attribute("test.agent", self._agent_name)
        span.set_attribute("test.runId", self._run_id)
        protocol = self._protocol_ctx.get("")
        if protocol:
            span.set_attribute("test.protocol", protocol)

    def on_end(self, span):  # type: ignore[override]
        return None

    def shutdown(self):  # type: ignore[override]
        return None

    def force_flush(self, timeout_millis: Optional[int] = None) -> bool:  # type: ignore[override]
        return True


def attach_test_processor(run_id: str) -> TestAttributesProcessor:
    processor = TestAttributesProcessor(SERVICE_NAME, run_id)
    provider = trace.get_tracer_provider()
    add = getattr(provider, "add_span_processor", None)
    if callable(add):
        add(processor)
        print(f"[telemetry] attached TestAttributesProcessor to {type(provider).__name__}")
    else:
        print(
            "[telemetry] global TracerProvider has no add_span_processor; "
            "spans will not be stamped (auto-instrumentation likely not present)"
        )
    return processor


# ---------------------------------------------------------------------------
# Weather tool
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
# Agent construction
# ---------------------------------------------------------------------------
def _instructions(use_tools: bool) -> str:
    return (
        "You are a helpful weather assistant. "
        + (
            "Use the get_current_weather tool to look up weather information when asked."
            if use_tools
            else "Answer weather questions using your knowledge. You do not have access to tools."
        )
    )


def _make_azure_chat(deployment: str, api_key: str) -> AzureChatOpenAI:
    return AzureChatOpenAI(
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        azure_deployment=deployment,
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
    """ChatOpenAI configured to use the OpenAI Responses API
    (POST /openai/v1/responses) against the Foundry endpoint.

    This is the only path in our setup that supports Responses API: LangChain's
    `AzureChatOpenAI` + `use_responses_api=True` is currently broken against the
    Azure OpenAI endpoint (returns 405 - see langchain-ai/langchain#31653), but
    pointing a plain `ChatOpenAI` at the Foundry `/openai/v1/` base URL routes
    successfully to `/openai/v1/responses`.
    """
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


def _build_agent(chat_model, use_tools: bool):
    instructions = _instructions(use_tools)

    if use_tools:
        agent = create_agent(
            chat_model,
            tools=[get_current_weather],
            system_prompt=instructions,
        )

        async def _run(user_prompt: str) -> str:
            result = await agent.ainvoke({"messages": [HumanMessage(content=user_prompt)]})
            messages = result.get("messages", [])
            for msg in reversed(messages):
                if isinstance(msg, AIMessage):
                    text = _extract_text(msg)
                    if text:
                        return text
            return ""

        return _run

    async def _run(user_prompt: str) -> str:
        response = await chat_model.ainvoke(
            [SystemMessage(content=instructions), HumanMessage(content=user_prompt)]
        )
        return _extract_text(response)

    return _run


def build_agents(api_key: str):
    agents = []
    for deployment in DEPLOYMENT_NAMES:
        use_tools = deployment not in NO_TOOL_DEPLOYMENTS

        try:
            chat_az = _make_azure_chat(deployment, api_key)
            agents.append(
                (f"{deployment} [completions]", _build_agent(chat_az, use_tools), "completions")
            )
        except Exception as ex:
            print(f"[build] failed completions {deployment}: {ex}")

        if use_tools:
            try:
                chat_f = _make_foundry_chat(deployment, api_key)
                agents.append(
                    (
                        f"{deployment} [foundry-completions]",
                        _build_agent(chat_f, use_tools),
                        "foundry-completions",
                    )
                )
            except Exception as ex:
                print(f"[build] failed foundry {deployment}: {ex}")

            try:
                chat_fr = _make_foundry_responses_chat(deployment, api_key)
                agents.append(
                    (
                        f"{deployment} [foundry-responses]",
                        _build_agent(chat_fr, use_tools),
                        "foundry-responses",
                    )
                )
            except Exception as ex:
                print(f"[build] failed foundry-responses {deployment}: {ex}")

    return agents


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
async def run_once(agents, test_processor: TestAttributesProcessor, run_label: str) -> int:
    tracer = trace.get_tracer(GENAI_SOURCE_NAME)

    print(f"\n=== Run: {run_label} ===")
    print(f"You: {USER_PROMPT}\n")

    async def _run(label, run_fn, protocol):
        test_processor.set_protocol(protocol)
        with tracer.start_as_current_span(
            f"langchain.agent.{label}", kind=SpanKind.INTERNAL
        ) as span:
            span.set_attribute("agent.label", label)
            span.set_attribute("agent.protocol", protocol)
            try:
                text = await run_fn(USER_PROMPT)
                span.set_attribute("agent.success", True)
                return (label, text, None)
            except Exception as ex:
                span.set_attribute("agent.success", False)
                span.set_attribute("agent.error", str(ex)[:512])
                return (label, None, ex)

    results = await asyncio.gather(*(_run(*a) for a in agents))
    successes = 0
    for label, text, error in results:
        print(f"--- [{label}] ---")
        if error is not None:
            print(f"  Error: {error}")
            continue
        successes += 1
        if text:
            print(f"  Assistant: {text}")
    print(f"\n[{run_label}] {successes}/{len(results)} agents succeeded")
    return successes


async def main() -> int:
    run_id = sys.argv[1] if len(sys.argv) > 1 else str(uuid.uuid4())
    print(f"Service: {SERVICE_NAME}")
    print(f"RunId:   {run_id}")

    test_processor = attach_test_processor(run_id)

    api_key = os.environ.get("AZURE_OPENAI_API_KEY", "")
    if not api_key:
        print("Error: AZURE_OPENAI_API_KEY is required.")
        return 1

    agents = build_agents(api_key)
    print(f"Built {len(agents)} agent variants.")

    loop_forever = os.environ.get("LOOP_FOREVER", "").lower() in ("1", "true", "yes")
    interval = int(os.environ.get("LOOP_INTERVAL_SECONDS", "60"))

    iteration = 0
    while True:
        iteration += 1
        await run_once(agents, test_processor, f"iteration-{iteration}")
        if not loop_forever:
            break
        print(f"\nSleeping {interval}s before next iteration...")
        await asyncio.sleep(interval)

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
