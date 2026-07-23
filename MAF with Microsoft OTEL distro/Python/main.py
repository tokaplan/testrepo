"""
WeatherChatMAFPython with Microsoft OpenTelemetry distro.

Multi-agent variant: demonstrates BOTH agent-as-tool nesting AND a
sequential workflow with sibling agent invocations.

Topology per protocol:
    SequentialWorkflow
    ├── MainAgent (orchestrator)
    │   └── tool: weather_data_agent.as_tool()
    │       └── invoke_agent[WeatherDataAgent]
    │           └── tool: get_current_weather (raw fn)
    └── VerifierAgent (no tools, judges main's output)
"""

import asyncio
import contextvars
import json
import os
import sys
import uuid
from typing import Annotated

# Ensure stdout/stderr can encode the LLM response text on Windows (cp1252 default).
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from azure.identity import DefaultAzureCredential
from opentelemetry import trace
from opentelemetry.sdk.trace import SpanProcessor as BaseSpanProcessor
from microsoft.opentelemetry import use_microsoft_opentelemetry

from agent_framework import (
    Agent,
    AgentExecutor,
    AgentExecutorResponse,
    WorkflowBuilder,
    tool,
)
from agent_framework.foundry import FoundryChatClient
from agent_framework.observability import enable_instrumentation
from agent_framework_openai import OpenAIChatClient, OpenAIChatCompletionClient

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
ENDPOINT = "https://alkap-mc9jji6o-eastus2.services.ai.azure.com/api/projects/alkap-mc9jji6o-eastus2_project"
BASE_URL = ENDPOINT + "/openai/v1/"
AZURE_OPENAI_ENDPOINT = "https://alkap-mc9jji6o-eastus2.cognitiveservices.azure.com"

# Multi-agent topology: assign a different deployment to each agent role so a
# single workflow run produces telemetry from multiple models. Each agent's
# chat spans carry their own gen_ai.request.model / gen_ai.response.model.
AGENT_DEPLOYMENTS = {
    "data":     "deployment-gpt-4o-mini",   # tool-caller (cheap, supports tools)
    "main":     "deployment-gpt-5.4-mini",  # orchestrator (smart, supports tools)
    "verifier": "deployment-gpt-4o",        # judge (chat model, no tools)
}

SERVICE_NAME = "WeatherChatMAFPython-MS-Distro"

DEFAULT_APP_INSIGHTS_CONNECTION_STRING = (
    "InstrumentationKey=06533fcd-4317-4b63-9c52-a518c492d907;"
    "IngestionEndpoint=https://eastus2-3.in.applicationinsights.azure.com/;"
    "LiveEndpoint=https://eastus2.livediagnostics.monitor.azure.com/;"
    "ApplicationId=66a40307-82d6-4baf-8886-37141dc8d391"
)


# ---------------------------------------------------------------------------
# Test span processor — adds runId / protocol attrs so we can filter the
# resulting telemetry. Independent of the distro's instrumentations.
# ---------------------------------------------------------------------------
class TestAgentSpanProcessor(BaseSpanProcessor):
    def __init__(self, agent_name: str, run_id: str):
        self._agent_name = agent_name
        self._run_id = run_id
        self._protocol_ctx = contextvars.ContextVar("test_protocol", default="")

    def set_protocol(self, protocol: str):
        self._protocol_ctx.set(protocol)

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


# ---------------------------------------------------------------------------
# Weather tool (raw function — wrapped by the WeatherDataAgent)
# ---------------------------------------------------------------------------
WEATHER_DATA = {
    "seattle, wa": (55, "Rainy"),
    "san francisco, ca": (63, "Foggy"),
    "new york, ny": (72, "Sunny"),
}


@tool(description="Gets the current weather for a given location.")
def get_current_weather(
    location: Annotated[str, "The city and state, e.g. San Francisco, CA"],
    unit: Annotated[str, "The temperature unit (defaults to fahrenheit)"] = "fahrenheit",
) -> str:
    temp_f, condition = WEATHER_DATA.get(location.lower(), (68, "Partly cloudy"))
    if unit == "celsius":
        temp = int((temp_f - 32) * 5.0 / 9.0)
        unit_label = "°C"
    else:
        temp = temp_f
        unit_label = "°F"

    print(f'[Tool] get_current_weather("{location}", "{unit}")')

    return json.dumps(
        {"location": location, "temperature": f"{temp}{unit_label}", "condition": condition}
    )


# ---------------------------------------------------------------------------
# Multi-agent construction
# ---------------------------------------------------------------------------
DATA_AGENT_INSTRUCTIONS = (
    "You are a weather data lookup agent. For each city the caller asks about, "
    "call get_current_weather exactly once and return the raw JSON results. "
    "Do not narrate, do not editorialize — just return the data."
)

MAIN_AGENT_INSTRUCTIONS = (
    "You are a friendly weather assistant. When the user asks about weather, "
    "delegate the actual lookups to the weather_data_agent tool — call it ONCE "
    "with all the cities the user mentioned, then summarize the data it returns "
    "in a single conversational reply."
)

VERIFIER_INSTRUCTIONS = (
    "You are a weather report verifier. You will be given the user's question "
    "and the weather assistant's reply. Check that:\n"
    "  1. Every city the user asked about is covered in the reply.\n"
    "  2. No additional cities (not asked about) appear in the reply.\n"
    "  3. The temperature/condition pairs are physically plausible "
    "(e.g. not 'Snowy' at 80°F).\n"
    "Reply with one line: either 'VERIFIED: <one-line summary>' "
    "or 'WARN: <reason>'. Do not call any tools."
)


def build_workflow(data_client, main_client, verifier_client, protocol_tag: str):
    """Build a {data → main} + {main → verifier} workflow.

    Each of the three agents takes its own chat client so that a single
    workflow run produces telemetry from up to 3 distinct deployments.
    """

    weather_data_agent = Agent(
        client=data_client,
        name=f"WeatherDataAgent-{protocol_tag}",
        description="Looks up weather for one or more cities via get_current_weather.",
        instructions=DATA_AGENT_INSTRUCTIONS,
        tools=[get_current_weather],
    )

    weather_data_tool = weather_data_agent.as_tool(
        name="weather_data_agent",
        description="Delegate to the weather data agent. Pass the list of cities the user asked about.",
        arg_name="cities",
        arg_description="The cities the user wants weather for, e.g. 'Seattle and San Francisco'.",
    )

    main_agent = Agent(
        client=main_client,
        name=f"MainWeatherAgent-{protocol_tag}",
        description="Friendly weather assistant that delegates lookups to a data agent.",
        instructions=MAIN_AGENT_INSTRUCTIONS,
        tools=[weather_data_tool],
    )

    verifier_agent = Agent(
        client=verifier_client,
        name=f"VerifierAgent-{protocol_tag}",
        description="Sanity-checks the main agent's weather report.",
        instructions=VERIFIER_INSTRUCTIONS,
    )

    # Wrap each agent in AgentExecutor with context_mode='full' so the verifier
    # receives the original user question PLUS the main agent's response, not
    # just the latest assistant message.
    main_exec = AgentExecutor(main_agent, id=f"main-{protocol_tag}", context_mode="full")
    verifier_exec = AgentExecutor(verifier_agent, id=f"verifier-{protocol_tag}", context_mode="full")

    workflow = (
        WorkflowBuilder(
            start_executor=main_exec,
            name=f"WeatherWorkflow-{protocol_tag}",
            output_from="all",
        )
        .add_edge(main_exec, verifier_exec)
        .build()
    )

    return workflow, main_exec.id, verifier_exec.id


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
async def main() -> int:
    run_id = sys.argv[1] if len(sys.argv) > 1 else str(uuid.uuid4())
    connection_string = os.environ.get(
        "APPLICATIONINSIGHTS_CONNECTION_STRING", DEFAULT_APP_INSIGHTS_CONNECTION_STRING
    )

    print(f"Service: {SERVICE_NAME}")
    print(f"RunId:   {run_id}")
    print(f"AppInsights: {connection_string[:60]}...")

    os.environ.setdefault("OTEL_SERVICE_NAME", SERVICE_NAME)
    use_microsoft_opentelemetry(
        enable_azure_monitor=True,
        azure_monitor_connection_string=connection_string,
    )

    enable_instrumentation(enable_sensitive_data=True)

    test_processor = TestAgentSpanProcessor(SERVICE_NAME, run_id)
    trace.get_tracer_provider().add_span_processor(test_processor)

    api_key = os.environ.get("AZURE_OPENAI_API_KEY", "")
    if not api_key:
        print("Error: AZURE_OPENAI_API_KEY is required.")
        return 1
    credential = DefaultAzureCredential()

    # -- Build a chat client per (protocol, agent role) so each agent uses
    # -- its assigned deployment. This lets a single run emit telemetry from
    # -- three distinct models across each protocol.
    def make_clients(protocol: str) -> dict:
        clients = {}
        for role, deployment in AGENT_DEPLOYMENTS.items():
            if protocol == "responses":
                clients[role] = OpenAIChatClient(
                    model=deployment,
                    base_url=BASE_URL,
                    api_key=api_key,
                    default_headers={"api-key": api_key},
                )
            elif protocol == "RAPI via foundry":
                clients[role] = FoundryChatClient(
                    project_endpoint=ENDPOINT,
                    model=deployment,
                    credential=credential,
                )
            elif protocol == "completions":
                clients[role] = OpenAIChatCompletionClient(
                    model=deployment,
                    azure_endpoint=AZURE_OPENAI_ENDPOINT,
                    api_key=api_key,
                )
            else:
                raise ValueError(f"Unknown protocol: {protocol}")
        return clients

    workflows = [
        ("responses", make_clients("responses")),
        ("RAPI via foundry", make_clients("RAPI via foundry")),
        ("completions", make_clients("completions")),
    ]

    user_prompt = "What's the weather like in Seattle and San Francisco?"
    print()
    print(f"You: {user_prompt}")
    print(f"Agent deployments: {AGENT_DEPLOYMENTS}")
    print()

    async def run_workflow(protocol: str, clients: dict):
        test_processor.set_protocol(protocol)
        protocol_tag = protocol.replace(" ", "-").replace("/", "-")
        try:
            workflow, main_id, verifier_id = build_workflow(
                data_client=clients["data"],
                main_client=clients["main"],
                verifier_client=clients["verifier"],
                protocol_tag=protocol_tag,
            )
            # Mixed streaming subagents in the workflow (matches MAF .NET):
            #   - workflow.run() (non-streaming) → Main + Verifier AgentExecutors
            #     each call agent.run(stream=False) → underlying chat client uses
            #     non-streaming HTTP.
            #   - Data agent is wrapped via Agent.as_tool(), whose internal
            #     wrapper hardcodes stream=True. So whenever Main's chat client
            #     invokes the weather_data_agent tool, the Data agent runs
            #     against its chat client with stream=True (SSE).
            # Net effect per workflow: Data streams, Main + Verifier do not.
            result = await workflow.run(user_prompt)
            return (protocol, result, main_id, verifier_id, None)
        except Exception as ex:
            return (protocol, None, None, None, ex)

    if os.environ.get("SEQUENTIAL", "").lower() in ("1", "true", "yes"):
        results = []
        for proto, clients in workflows:
            results.append(await run_workflow(proto, clients))
    else:
        results = await asyncio.gather(
            *(run_workflow(proto, clients) for proto, clients in workflows)
        )

    successes = 0
    for protocol, result, main_id, verifier_id, error in results:
        print(f"--- [{protocol}] ---")
        if error is not None:
            print(f"  Error: {error}")
            continue
        successes += 1

        # With output_from='all', both executors yield AgentResponse outputs.
        # Order matches execution order: [main, verifier].
        outputs = result.get_outputs()
        main_text = outputs[0].text if len(outputs) >= 1 and hasattr(outputs[0], "text") else None
        verifier_text = outputs[1].text if len(outputs) >= 2 and hasattr(outputs[1], "text") else None

        if main_text:
            print(f"  Assistant: {main_text}")
        if verifier_text:
            print(f"  Verifier:  {verifier_text}")
        print()

    print()
    print(f"[run] {successes}/{len(results)} workflows succeeded")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
