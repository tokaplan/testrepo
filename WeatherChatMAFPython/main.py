"""
WeatherChatMAFPython - a console app that uses the Microsoft Agent Framework
(MAF) Python SDK with tool calling to answer weather questions, with OTEL
telemetry (including agent spans) exported to Application Insights.

This is a Python port of the C# WeatherChatMAF project.
"""

import asyncio
import contextvars
import json
import os
import sys
import uuid
from typing import Annotated

from opentelemetry import trace, metrics
from opentelemetry.sdk.trace import TracerProvider, SpanProcessor as BaseSpanProcessor
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from azure.monitor.opentelemetry.exporter import (
    AzureMonitorTraceExporter,
    AzureMonitorMetricExporter,
)
from opentelemetry.instrumentation.openai_v2 import OpenAIInstrumentor

from agent_framework import Agent, tool
from agent_framework.observability import enable_instrumentation
from agent_framework.foundry import FoundryChatClient
from agent_framework_openai import OpenAIChatClient, OpenAIChatCompletionClient

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
ENDPOINT = "https://alkap-mc9jji6o-eastus2.services.ai.azure.com/api/projects/alkap-mc9jji6o-eastus2_project"
BASE_URL = ENDPOINT + "/openai/v1/"
# Azure OpenAI endpoint for Chat Completions (Foundry /v1/ path doesn't work for all models with Bearer auth)
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

# Deployments that don't support tool calling
NO_TOOL_DEPLOYMENTS = {
    "deployment-Phi-4",
    "deployment-DeepSeek-R1",
}

# Deployments that support the Responses API
RESPONSES_API_DEPLOYMENTS = {
    "deployment-gpt-5.4-mini",
    "deployment-gpt-4o",
    "deployment-gpt-4o-mini",
    "deployment-o4-mini",
}
FAKE_MODE = False
USE_GLOBAL = False

APP_INSIGHTS_CONNECTION_STRING = (
    "InstrumentationKey=2ccfb7eb-f0b9-47aa-bf42-75b4f78c1e23;"
    "IngestionEndpoint=https://westcentralus-6.in.aimon.applicationinsights.azure.com/;"
    "LiveEndpoint=https://westcentralus.livediagnostics.aimon.monitor.azure.com/;"
    "AADAudience=https://monitor.azure.com/;"
    "ApplicationId=69c761e5-ed5d-4ab5-9132-fd27e7d39e2d"
)


def _build_connection_string() -> str:
    """Optionally strip IngestionEndpoint and LiveEndpoint when using global."""
    cs = APP_INSIGHTS_CONNECTION_STRING
    if USE_GLOBAL:
        parts = [
            p
            for p in cs.split(";")
            if p and not p.strip().lower().startswith(("ingestionendpoint=", "liveendpoint="))
        ]
        cs = ";".join(parts)
    return cs


# ---------------------------------------------------------------------------
# OpenTelemetry setup
# ---------------------------------------------------------------------------
FAKE_GENAI_SOURCE_NAME = "FakeGenAI"


class TestAgentSpanProcessor(BaseSpanProcessor):
    """Stamps every span with test.agent, test.runId, and test.protocol attributes."""
    def __init__(self, agent_name: str, run_id: str):
        self._agent_name = agent_name
        self._run_id = run_id
        self._protocol_ctx = contextvars.ContextVar("test_protocol", default="")

    def set_protocol(self, protocol: str):
        """Set the protocol for the current context (call before agent.run)."""
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

def configure_telemetry(connection_string: str, run_id: str):
    """Configure OTEL tracing & metrics with Azure Monitor export."""

    resource = Resource.create({
        "service.name": "WeatherChatMAFPython",
    })

    # -- Tracing --
    test_processor = TestAgentSpanProcessor("WeatherChatMAFPython", run_id)
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(test_processor)
    tracer_provider.add_span_processor(
        BatchSpanProcessor(
            AzureMonitorTraceExporter(
                connection_string=connection_string,
                sampling_ratio=1.0,  # No sampling — export everything
            )
        )
    )
    trace.set_tracer_provider(tracer_provider)

    # -- Metrics --
    metric_reader = PeriodicExportingMetricReader(
        AzureMonitorMetricExporter(connection_string=connection_string),
        export_interval_millis=60_000,
    )
    meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
    metrics.set_meter_provider(meter_provider)

    # Instrument the OpenAI SDK for GenAI semantic conventions
    OpenAIInstrumentor().instrument()

    # Enable MAF's built-in telemetry (agent spans, gen_ai metrics)
    enable_instrumentation()

    return tracer_provider, meter_provider, test_processor


# ---------------------------------------------------------------------------
# Fake GenAI span (mirrors the C# EmitFakeGenAIDependency)
# ---------------------------------------------------------------------------
def emit_fake_genai_dependency():
    tracer = trace.get_tracer(FAKE_GENAI_SOURCE_NAME)
    with tracer.start_as_current_span(
        "chat deployment-gpt-5.4-mini", kind=trace.SpanKind.CLIENT
    ) as span:
        span.set_attribute("fake_span", True)
        span.set_attribute("gen_ai.operation.name", "chat")
        span.set_attribute("gen_ai.request.model", "deployment-gpt-5.4-mini")
        span.set_attribute("gen_ai.response.finish_reasons", "stop")
        span.set_attribute("gen_ai.response.id", "chatcmpl-DRlntxPA5EynvSpG4lxuG5c7q4l9B")
        span.set_attribute("gen_ai.response.model", "gpt-5.4-mini-2026-03-17")
        span.set_attribute("gen_ai.system", "openai")
        span.set_attribute("gen_ai.usage.input_tokens", 44)
        span.set_attribute("gen_ai.usage.output_tokens", 38)
        span.set_attribute("server.address", ENDPOINT)
        span.set_attribute("server.port", 443)

    print("[FakeGenAI] Emitted fake GenAI dependency span with cost-enrichment attributes.")


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
    connection_string = _build_connection_string()
    tracer_provider, meter_provider, test_processor = configure_telemetry(connection_string, run_id)

    print("Enter your Azure OpenAI API key: ")
    print(f"AppInsights: {connection_string}")

    if FAKE_MODE:
        emit_fake_genai_dependency()
        tracer_provider.force_flush()
        meter_provider.force_flush()
        return 0

    api_key = os.environ.get("AZURE_OPENAI_API_KEY", "")
    # api_key = input().strip()

    if not api_key:
        print("Error: An API key is required.")
        return 1

    # -- Build one MAF agent per deployment --------------------------------
    # For models that support Responses API, create two agents: one via Responses, one via Chat Completions
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
            # Responses API agent (OpenAIChatClient)
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

            # Responses API agent (FoundryChatClient)
            from azure.core.credentials import AzureKeyCredential
            client_foundry = FoundryChatClient(
                project_endpoint=ENDPOINT,
                model=deployment,
                credential=AzureKeyCredential(api_key),
            )
            agent_foundry = Agent(
                client=client_foundry,
                instructions=instructions,
                name=f"WeatherAgent-{deployment}-foundry",
                tools=agent_tools,
            )
            agents.append((f"{deployment} [RAPI via foundry]", agent_foundry, "RAPI via foundry"))

            # Chat Completions API agent for the same model
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
            # Chat Completions only
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

    # -- Invoke all agents in parallel -------------------------------------
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

    for deployment, response, error in results:
        print(f"--- [{deployment}] ---")
        if error is not None:
            print(f"  Error: {error}")
            continue

        if response.text:
            print(f"  Assistant: {response.text}")

        print()

    # Flush telemetry before exit
    tracer_provider.force_flush()
    meter_provider.force_flush()

    print()
    print("Telemetry flushed to Application Insights.")
    return 0


if __name__ == "__main__":
    exit(asyncio.run(main()))
