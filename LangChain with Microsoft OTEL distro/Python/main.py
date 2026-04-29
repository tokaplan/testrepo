"""
LangChainPython with Microsoft OpenTelemetry distro - same agent as the
sibling LangChainPython project.

This file contains zero OpenTelemetry references. Telemetry is supplied by
an out-of-tree instrumentation setup (the Microsoft OpenTelemetry distro,
configured separately) so the agent code itself stays clean.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from typing import Annotated

from langchain_openai import AzureChatOpenAI, ChatOpenAI
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from langchain.agents import create_agent

# ---------------------------------------------------------------------------
# Configuration - mirrors the sibling LangChainPython agent
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

SERVICE_NAME = "LangChainPython-MS-Distro"
USER_PROMPT = "What's the weather like in Seattle and San Francisco?"

# data-1 in alkaplan-longchain.
DEFAULT_APP_INSIGHTS_CONNECTION_STRING = (
    "InstrumentationKey=06533fcd-4317-4b63-9c52-a518c492d907;"
    "IngestionEndpoint=https://eastus2-3.in.applicationinsights.azure.com/;"
    "LiveEndpoint=https://eastus2.livediagnostics.monitor.azure.com/;"
    "ApplicationId=66a40307-82d6-4baf-8886-37141dc8d391"
)


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
async def run_once(agents, run_label: str) -> int:
    print(f"\n=== Run: {run_label} ===")
    print(f"You: {USER_PROMPT}\n")

    async def _run(label, run_fn, protocol):
        try:
            text = await run_fn(USER_PROMPT)
            return (label, text, None)
        except Exception as ex:
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
        await run_once(agents, f"iteration-{iteration}")
        if not loop_forever:
            break
        print(f"\nSleeping {interval}s before next iteration...")
        await asyncio.sleep(interval)

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
