"""
WeatherChatMAFPython with Microsoft OpenTelemetry distro.

Same MAF agent as the sibling WeatherChatMAFPython project, but the only
telemetry setup is a single call to `use_microsoft_opentelemetry()` from
Microsoft's `microsoft-opentelemetry` distro. The distro's bundled
`AgentFrameworkInstrumentor` and `OpenAIInstrumentor` (auto-discovered via
`_SUPPORTED_INSTRUMENTED_LIBRARIES`) emit agent-level + chat-level GenAI
spans with no manual instrumentation in this file.
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

from agent_framework import Agent, tool
from agent_framework.foundry import FoundryChatClient
from agent_framework.observability import enable_instrumentation
from agent_framework_openai import OpenAIChatClient, OpenAIChatCompletionClient

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
ENDPOINT = "https://alkap-mc9jji6o-eastus2.services.ai.azure.com/api/projects/alkap-mc9jji6o-eastus2_project"
BASE_URL = ENDPOINT + "/openai/v1/"
AZURE_OPENAI_ENDPOINT = "https://alkap-mc9jji6o-eastus2.cognitiveservices.azure.com"

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

RESPONSES_API_DEPLOYMENTS = {
    "deployment-gpt-5.4-mini",
    "deployment-gpt-4o",
    "deployment-gpt-4o-mini",
    "deployment-o4-mini",
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
# Weather tool
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

    # The SINGLE call that wires up Microsoft's OTEL distro - exporter +
    # bundled instrumentations (langchain, openai, openai_agents,
    # semantic_kernel, agent_framework, ...).
    os.environ.setdefault("OTEL_SERVICE_NAME", SERVICE_NAME)
    use_microsoft_opentelemetry(
        enable_azure_monitor=True,
        azure_monitor_connection_string=connection_string,
        sampling_ratio=1.0,
    )

    # Flip the agent-framework-side flag that makes MAF actually emit
    # invoke_agent / execute_tool spans. The MS distro's bundled
    # `AgentFrameworkInstrumentor` only enriches spans MAF already emits
    # — it does NOT enable MAF's own instrumentation. This is analogous
    # to `AppContext.SetSwitch("OpenAI.Experimental.EnableOpenTelemetry", true)`
    # on the .NET side: the toggle lives in the agent SDK itself, not in
    # the OTel distro.
    enable_instrumentation()

    # Add our own test-tagging processor so spans get test.agent/test.runId
    # for filtering. Must happen AFTER use_microsoft_opentelemetry so the
    # tracer provider has been registered globally.
    test_processor = TestAgentSpanProcessor(SERVICE_NAME, run_id)
    trace.get_tracer_provider().add_span_processor(test_processor)

    # Auth split:
    #   - OpenAIChatClient / OpenAIChatCompletionClient use a static api_key
    #     (Foundry's /openai/v1/ and Azure OpenAI both accept it; the openai
    #     SDK puts it on Authorization: Bearer <key>).
    #   - FoundryChatClient requires a TokenCredential (no api_key path), so
    #     it gets DefaultAzureCredential. The azure-core pipeline acquires
    #     tokens with the correct ai.azure.com audience by itself.
    api_key = os.environ.get("AZURE_OPENAI_API_KEY", "")
    if not api_key:
        print("Error: AZURE_OPENAI_API_KEY is required.")
        return 1
    credential = DefaultAzureCredential()

    # -- Build one MAF agent per deployment --------------------------------
    agents = []
    for deployment in DEPLOYMENT_NAMES:
        use_tools = deployment not in NO_TOOL_DEPLOYMENTS
        instructions = (
            "You are a helpful weather assistant. "
            + ("Use the get_current_weather tool to look up weather information when asked."
               if use_tools else
               "Answer weather questions using your knowledge. You do not have access to tools.")
        )
        agent_tools = [get_current_weather] if use_tools else None

        if deployment in RESPONSES_API_DEPLOYMENTS:
            client_resp = OpenAIChatClient(
                model=deployment,
                base_url=BASE_URL,
                api_key=api_key,
                default_headers={"api-key": api_key},
            )
            agent_resp = Agent(
                client=client_resp,
                instructions=instructions,
                name=f"WeatherAgent-{deployment}-responses",
                tools=agent_tools,
            )
            agents.append((f"{deployment} [responses]", agent_resp, "responses"))

            client_foundry = FoundryChatClient(
                project_endpoint=ENDPOINT,
                model=deployment,
                credential=credential,
            )
            agent_foundry = Agent(
                client=client_foundry,
                instructions=instructions,
                name=f"WeatherAgent-{deployment}-foundry",
                tools=agent_tools,
            )
            agents.append((f"{deployment} [RAPI via foundry]", agent_foundry, "RAPI via foundry"))

            client_cc = OpenAIChatCompletionClient(
                model=deployment,
                azure_endpoint=AZURE_OPENAI_ENDPOINT,
                api_key=api_key,
            )
            agent_cc = Agent(
                client=client_cc,
                instructions=instructions,
                name=f"WeatherAgent-{deployment}-completions",
                tools=agent_tools,
            )
            agents.append((f"{deployment} [completions]", agent_cc, "completions"))
        else:
            client = OpenAIChatCompletionClient(
                model=deployment,
                azure_endpoint=AZURE_OPENAI_ENDPOINT,
                api_key=api_key,
            )
            agent = Agent(
                client=client,
                instructions=instructions,
                name=f"WeatherAgent-{deployment}",
                tools=agent_tools,
            )
            agents.append((f"{deployment} [completions]", agent, "completions"))

    user_prompt = "What's the weather like in Seattle and San Francisco?"

    print()
    print(f"You: {user_prompt}")
    print()

    async def run_agent(label, agent, protocol):
        test_processor.set_protocol(protocol)
        try:
            response = await agent.run(user_prompt)
            return (label, response, None)
        except Exception as ex:
            return (label, None, ex)

    results = await asyncio.gather(
        *(run_agent(label, ag, proto) for label, ag, proto in agents)
    )

    successes = 0
    for deployment, response, error in results:
        print(f"--- [{deployment}] ---")
        if error is not None:
            print(f"  Error: {error}")
            continue
        successes += 1
        if response.text:
            print(f"  Assistant: {response.text}")
        print()

    print()
    print(f"[run] {successes}/{len(results)} agents succeeded")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
