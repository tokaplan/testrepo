using System.ClientModel;
using System.ComponentModel;
using System.Diagnostics;
using System.Text.Json;
using Azure.Core;
using Azure.Core.Pipeline;
using Azure.Monitor.OpenTelemetry.Exporter;
using Microsoft.SemanticKernel;
using Microsoft.SemanticKernel.Agents;
using Microsoft.SemanticKernel.ChatCompletion;
using OpenTelemetry;
using OpenTelemetry.Metrics;
using OpenTelemetry.Resources;
using OpenTelemetry.Trace;

// ---------------------------------------------------------------------------
// WeatherChat - a console app that uses a Semantic Kernel ChatCompletionAgent
// with tool calling to answer weather questions, with OTEL telemetry
// (including agent spans) exported to Application Insights.
// ---------------------------------------------------------------------------

const string endpoint = "https://alkap-mc9jji6o-eastus2.services.ai.azure.com/api/projects/alkap-mc9jji6o-eastus2_project";
string[] deploymentNames = ["deployment-gpt-5.4-mini", "deployment-Phi-4", "deployment-DeepSeek-R1", "deployment-Llama-3.3-70B-Instruct"];
string deploymentName = deploymentNames[0];

bool useGlobal = false;

//const string appInsightsConnectionString = "InstrumentationKey=978264a8-7be3-47ac-8c4e-fe3e62866da2;IngestionEndpoint=https://centraluseuap-0.in.applicationinsights.azure.com/;LiveEndpoint=https://centraluseuap.livediagnostics.monitor.azure.com/;ApplicationId=aec2eac5-dab8-400c-9fec-de7d03a0eec2"; //genai-roi-test-11

string appInsightsConnectionString = "InstrumentationKey=2ccfb7eb-f0b9-47aa-bf42-75b4f78c1e23;IngestionEndpoint=https://westcentralus-6.in.aimon.applicationinsights.azure.com/;LiveEndpoint=https://westcentralus.livediagnostics.aimon.monitor.azure.com/;AADAudience=https://monitor.azure.com/;ApplicationId=69c761e5-ed5d-4ab5-9132-fd27e7d39e2d"; //genai-global-path-1
//string appInsightsConnectionString = "InstrumentationKey=2ccfb7eb-f0b9-47aa-bf42-75b4f78c1e23;IngestionEndpoint=https://breeze.aimon.applicationinsights.io;AADAudience=https://monitor.azure.com/;ApplicationId=69c761e5-ed5d-4ab5-9132-fd27e7d39e2d"; //genai-global-path-1 global

if (useGlobal)
{
    // Strip IngestionEndpoint and LiveEndpoint from the connection string at runtime
    var strippedParts = appInsightsConnectionString
        .Split(';', StringSplitOptions.RemoveEmptyEntries)
        .Where(part =>
        {
            var key = part.Split('=', 2)[0].Trim();
            return !key.Equals("IngestionEndpoint", StringComparison.OrdinalIgnoreCase)
                && !key.Equals("LiveEndpoint", StringComparison.OrdinalIgnoreCase);
        });
    appInsightsConnectionString = string.Join(";", strippedParts);
}

// Opt in to experimental OpenTelemetry for both OpenAI SDK and Semantic Kernel
AppContext.SetSwitch("OpenAI.Expersimental.EnableOpenTelemetry", true);
AppContext.SetSwitch("Microsoft.SemanticKernel.Experimental.GenAI.EnableOTelDiagnostics", true);

// ----- Configure OpenTelemetry tracing & metrics ---------------------------
const string FakeGenAISourceName = "FakeGenAI";
ActivitySource fakeGenAISource = new(FakeGenAISourceName);

using var tracerProvider = Sdk.CreateTracerProviderBuilder()
    .ConfigureResource(r => r.AddService("WeatherChat"))
    .AddProcessor(new TestAgentProcessor("WeatherChat", "completions"))
    .AddSource("OpenAI.*")
    .AddSource("Microsoft.SemanticKernel*")
    .AddSource(FakeGenAISourceName)
    .AddHttpClientInstrumentation()
    .AddAzureMonitorTraceExporter(o =>
    {
        o.ConnectionString = appInsightsConnectionString;
        o.AddPolicy(new CustomHeaderPolicy(), HttpPipelinePosition.PerCall);
    })
    .Build();

using var meterProvider = Sdk.CreateMeterProviderBuilder()
    .AddMeter("OpenAI.*")
    .AddMeter("Microsoft.SemanticKernel*")
    .AddRuntimeInstrumentation()
    .AddHttpClientInstrumentation()
    .AddAzureMonitorMetricExporter(o =>
    {
        o.ConnectionString = appInsightsConnectionString;
        o.AddPolicy(new CustomHeaderPolicy(), HttpPipelinePosition.PerCall);
    })
    .Build();

// ----- Prompt for API key --------------------------------------------------
Console.WriteLine("Enter your Azure OpenAI API key: ");
Console.WriteLine($@"AppInsights: {appInsightsConnectionString}");

bool fakeMode = false;
if(fakeMode)
{
    // Emit a fake GenAI dependency with all attributes Breeze's GenAICostEnrichment needs
    EmitFakeGenAIDependency(fakeGenAISource);

    tracerProvider?.ForceFlush();
    meterProvider?.ForceFlush();

    return 0;
}

string? apiKey = Environment.GetEnvironmentVariable("AZURE_OPENAI_API_KEY");// Console.ReadLine()?.Trim();

if (string.IsNullOrWhiteSpace(apiKey))
{
    Console.Error.WriteLine("Error: An API key is required.");
    return 1;
}

// ----- Build kernel with Azure OpenAI and weather plugin -------------------
var builder = Kernel.CreateBuilder();
builder.AddAzureOpenAIChatCompletion(deploymentName, endpoint, apiKey);
builder.Plugins.AddFromType<WeatherPlugin>();

Kernel kernel = builder.Build();

// ----- Create the agent ----------------------------------------------------
ChatCompletionAgent agent = new()
{
    Name = "WeatherAgent",
    Description = "A helpful weather assistant that can look up current weather.",
    Instructions = "You are a helpful weather assistant. Use the get_current_weather tool to look up weather information when asked.",
    Kernel = kernel
};

string userPrompt = "What's the weather like in Seattle and San Francisco?";

Console.WriteLine();
Console.WriteLine($"You: {userPrompt}");
Console.WriteLine();

// ----- Invoke the agent (SK handles the tool-calling loop) -----------------
try
{
    ChatHistoryAgentThread thread = new();

    await foreach (AgentResponseItem<ChatMessageContent> response in agent.InvokeAsync(
        new ChatMessageContent(AuthorRole.User, userPrompt), thread))
    {
        if (response.Message.Role == AuthorRole.Assistant && !string.IsNullOrWhiteSpace(response.Message.Content))
        {
            Console.WriteLine($"Assistant: {response.Message.Content}");
        }
    }
}
catch (ClientResultException ex)
{
    Console.Error.WriteLine($"API error: {ex.Message}");
    return 1;
}

// Flush telemetry before exit
tracerProvider?.ForceFlush();
meterProvider?.ForceFlush();

Console.WriteLine();
Console.WriteLine("Telemetry flushed to Application Insights.");
return 0;

// ---------------------------------------------------------------------------
// Fake GenAI dependency - emits a span with all attributes that Breeze's
// GenAICostEnrichment.cs reads for cost calculation.
//
// The enrichment requires:
//   1. The item is a dependency (Client/Internal span → RemoteDependencyData)
//   2. gen_ai.operation.name is present and NOT in the excluded set
//      (excluded: retrieval, execute_tool, invoke_agent, create_agent)
//   3. Token counts: gen_ai.usage.input_tokens and/or gen_ai.usage.output_tokens
//   4. Model: gen_ai.response.model (preferred) or gen_ai.request.model (fallback)
//   5. Provider: gen_ai.provider.name (preferred) or gen_ai.system (fallback)
//   6. Optional: gen_ai.usage.cache_read.input_tokens,
//                gen_ai.usage.cache_creation.input_tokens
// ---------------------------------------------------------------------------
static void EmitFakeGenAIDependency(ActivitySource source)
{
    using (var activity = source.StartActivity("chat deployment-gpt-5.4-mini", ActivityKind.Client))
    {
        if (activity is null)
            return;

        activity.SetTag("fake_span", "true");
        activity.SetTag("gen_ai.operation.name", "chat");
        activity.SetTag("gen_ai.request.model", "deployment-gpt-5.4-mini");
        activity.SetTag("gen_ai.response.finish_reasons", "stop");
        activity.SetTag("gen_ai.response.id", "chatcmpl-DRlntxPA5EynvSpG4lxuG5c7q4l9B");
        activity.SetTag("gen_ai.response.model", "gpt-5.4-mini-2026-03-17");
        activity.SetTag("gen_ai.system", "openai");
        activity.SetTag("gen_ai.usage.input_tokens", 44);
        activity.SetTag("gen_ai.usage.output_tokens", 38);

        // Required by Azure Monitor exporter to construct a valid RemoteDependencyData envelope
        activity.SetTag("server.address", endpoint);
        activity.SetTag("server.port", 443);
        activity.SetStatus(ActivityStatusCode.Ok);
    }

    Console.WriteLine("[FakeGenAI] Emitted fake GenAI dependency span with cost-enrichment attributes.");
}

// ---------------------------------------------------------------------------
// Processor that stamps every span with test.agent
// ---------------------------------------------------------------------------
sealed class TestAgentProcessor(string agentName, string protocol) : BaseProcessor<Activity>
{
    public override void OnStart(Activity data)
    {
        data.SetTag("test.agent", agentName);
        data.SetTag("test.protocol", protocol);
    }
}

// ---------------------------------------------------------------------------
// Custom HTTP pipeline policy - adds a header to every Breeze request
// ---------------------------------------------------------------------------
sealed class CustomHeaderPolicy : HttpPipelinePolicy
{
    public override void Process(HttpMessage message, ReadOnlyMemory<HttpPipelinePolicy> pipeline)
    {
        AddCustomHeader(message);
        ProcessNext(message, pipeline);
    }

    public override ValueTask ProcessAsync(HttpMessage message, ReadOnlyMemory<HttpPipelinePolicy> pipeline)
    {
        AddCustomHeader(message);
        return ProcessNextAsync(message, pipeline);
    }

    private static void AddCustomHeader(HttpMessage message)
    {
        message.Request.Headers.SetValue("x-ms-smoke-test-endpoint", "true");
    }
}

// ---------------------------------------------------------------------------
// Weather plugin - exposes the weather tool as a KernelFunction
// ---------------------------------------------------------------------------
sealed class WeatherPlugin
{
    [KernelFunction("get_current_weather")]
    [Description("Gets the current weather for a given location.")]
    public string GetCurrentWeather(
        [Description("The city and state, e.g. San Francisco, CA")] string location,
        [Description("The temperature unit (defaults to fahrenheit)")] string unit = "fahrenheit")
    {
        var weatherData = new Dictionary<string, (int TempF, string Condition)>(StringComparer.OrdinalIgnoreCase)
        {
            ["Seattle, WA"] = (55, "Rainy"),
            ["San Francisco, CA"] = (63, "Foggy"),
            ["New York, NY"] = (72, "Sunny"),
        };

        if (!weatherData.TryGetValue(location, out var data))
            data = (68, "Partly cloudy");

        int temp = unit == "celsius" ? (int)((data.TempF - 32) * 5.0 / 9.0) : data.TempF;
        string unitLabel = unit == "celsius" ? "°C" : "°F";

        Console.WriteLine($"[Tool] get_current_weather(\"{location}\", \"{unit}\")");

        return JsonSerializer.Serialize(new
        {
            location,
            temperature = $"{temp}{unitLabel}",
            condition = data.Condition
        });
    }
}
