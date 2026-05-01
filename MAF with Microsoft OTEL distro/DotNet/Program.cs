using System.ComponentModel;
using System.Diagnostics;
using System.Text.Json;
using Azure.AI.OpenAI;
using Microsoft.Agents.AI;
using Microsoft.Extensions.AI;
using Microsoft.OpenTelemetry;
using OpenAI;
using OpenTelemetry;
using OpenTelemetry.Resources;
using OpenTelemetry.Trace;

#pragma warning disable OPENAI001 // ResponsesClient is experimental

// ---------------------------------------------------------------------------
// WeatherChatMAF with Microsoft OpenTelemetry distro
//
// Same MAF agent as the sibling WeatherChatMAF project, but its only
// telemetry setup is Microsoft's `Microsoft.OpenTelemetry` distro, wired
// up via `OpenTelemetrySdk.Create(otel => otel.UseMicrosoftOpenTelemetry(...))`.
// The distro turns on its bundled Agent Framework / OpenAI / Azure OpenAI
// activity sources by default, so there are no manual `AddSource(...)` or
// `AddAzureMonitorTraceExporter(...)` calls in this file.
// ---------------------------------------------------------------------------

const string endpoint = "https://alkap-mc9jji6o-eastus2.services.ai.azure.com/api/projects/alkap-mc9jji6o-eastus2_project";
const string azureOpenAIEndpoint = "https://alkap-mc9jji6o-eastus2.cognitiveservices.azure.com";
string[] deploymentNames = ["deployment-gpt-5.4-mini", "deployment-gpt-4o", "deployment-gpt-4o-mini", "deployment-o4-mini", "deployment-Phi-4", "deployment-DeepSeek-R1", "deployment-Llama-3.3-70B-Instruct"];
HashSet<string> noToolDeployments = ["deployment-Phi-4", "deployment-DeepSeek-R1"];
HashSet<string> responsesApiDeployments = ["deployment-gpt-5.4-mini", "deployment-gpt-4o", "deployment-gpt-4o-mini", "deployment-o4-mini"];

string runId = args.Length > 0 ? args[0] : Guid.NewGuid().ToString();
const string ServiceName = "WeatherChatMAF-MS-Distro";

string appInsightsConnectionString =
    Environment.GetEnvironmentVariable("APPLICATIONINSIGHTS_CONNECTION_STRING")
    ?? "InstrumentationKey=06533fcd-4317-4b63-9c52-a518c492d907;"
       + "IngestionEndpoint=https://eastus2-3.in.applicationinsights.azure.com/;"
       + "LiveEndpoint=https://eastus2.livediagnostics.monitor.azure.com/;"
       + "ApplicationId=66a40307-82d6-4baf-8886-37141dc8d391";

Console.WriteLine($"Service: {ServiceName}");
Console.WriteLine($"RunId:   {runId}");
Console.WriteLine($"AppInsights: {appInsightsConnectionString[..60]}...");

// Opt in to experimental OpenTelemetry for the OpenAI SDK so that the
// distro's bundled OpenAI/Azure OpenAI instrumentation actually emits spans.
AppContext.SetSwitch("OpenAI.Experimental.EnableOpenTelemetry", true);

// ---------------------------------------------------------------------------
// The SINGLE call that wires up Microsoft's OpenTelemetry distro - exporter
// + bundled instrumentations (Agent Framework, OpenAI, Azure OpenAI, HTTP,
// Azure SDK, ...). The trailing TestAgentProcessor adds test.agent /
// test.runId / test.protocol attributes so this run can be filtered.
// ---------------------------------------------------------------------------
using var sdk = OpenTelemetrySdk.Create(otel =>
{
    otel.ConfigureResource(r => r.AddService(ServiceName));
    otel.UseMicrosoftOpenTelemetry(o =>
    {
        o.Exporters = ExportTarget.AzureMonitor;
        o.AzureMonitor.ConnectionString = appInsightsConnectionString;
    });
    otel.WithTracing(b => b.AddProcessor(new TestAgentProcessor(ServiceName, runId)));
});

string? apiKey = Environment.GetEnvironmentVariable("AZURE_OPENAI_API_KEY");
if (string.IsNullOrWhiteSpace(apiKey))
{
    Console.Error.WriteLine("Error: AZURE_OPENAI_API_KEY environment variable is required.");
    return 1;
}

// ----- Build one MAF agent per deployment, sharing the same client ---
var baseUrl = endpoint + "/openai/v1/";
var openAIClient = new OpenAIClient(
    new System.ClientModel.ApiKeyCredential(apiKey),
    new OpenAIClientOptions { Endpoint = new Uri(baseUrl) });
var azureClient = new AzureOpenAIClient(
    new Uri(azureOpenAIEndpoint),
    new System.ClientModel.ApiKeyCredential(apiKey));
var tools = new List<AITool> { AIFunctionFactory.Create(WeatherPlugin.GetCurrentWeather) };

var agents = new List<(string label, AIAgent agent, string protocol)>();

foreach (var deployment in deploymentNames)
{
    bool useTools = !noToolDeployments.Contains(deployment);
    string instructions = useTools
        ? "You are a helpful weather assistant. Use the get_current_weather tool to look up weather information when asked."
        : "You are a helpful weather assistant. Answer weather questions using your knowledge. You do not have access to tools.";

    if (responsesApiDeployments.Contains(deployment))
    {
        // Responses API agent
        var respClient = openAIClient.GetResponsesClient().AsIChatClient(defaultModelId: deployment);
        AIAgent respAgent = new ChatClientAgent(respClient,
            instructions: instructions, name: $"WeatherAgent-{deployment}-responses",
            description: "Weather assistant", tools: tools);
        agents.Add(($"{deployment} [responses]", new OpenTelemetryAgent(respAgent), "responses"));

        // Chat Completions API agent for the same model
        var ccClient = azureClient.GetChatClient(deployment).AsIChatClient();
        AIAgent ccAgent = new ChatClientAgent(ccClient,
            instructions: instructions, name: $"WeatherAgent-{deployment}-completions",
            description: "Weather assistant", tools: tools);
        agents.Add(($"{deployment} [completions]", new OpenTelemetryAgent(ccAgent), "completions"));
    }
    else
    {
        var ccClient = azureClient.GetChatClient(deployment).AsIChatClient();
        AIAgent ccAgent = new ChatClientAgent(ccClient,
            instructions: instructions, name: $"WeatherAgent-{deployment}",
            description: "Weather assistant", tools: useTools ? tools : null);
        agents.Add(($"{deployment} [completions]", new OpenTelemetryAgent(ccAgent), "completions"));
    }
}

string userPrompt = "What's the weather like in Seattle and San Francisco?";

Console.WriteLine();
Console.WriteLine($"You: {userPrompt}");
Console.WriteLine();

// ----- Invoke all agents sequentially to keep the test.protocol stamp deterministic ---
var results = new List<(string label, AgentResponse? response, Exception? error)>();
foreach (var (label, agent, protocol) in agents)
{
    TestAgentProcessor.SetProtocol(protocol);
    try
    {
        AgentResponse response = await agent.RunAsync(userPrompt);
        results.Add((label, response, null));
    }
    catch (Exception ex)
    {
        results.Add((label, null, ex));
    }
}

int successes = 0;
foreach (var (deployment, response, error) in results)
{
    Console.WriteLine($"--- [{deployment}] ---");
    if (error is not null)
    {
        Console.Error.WriteLine($"  Error: {error.Message}");
        continue;
    }
    successes++;

    foreach (var message in response!.Messages)
    {
        if (message.Role == ChatRole.Assistant && !string.IsNullOrWhiteSpace(message.Text))
        {
            Console.WriteLine($"  Assistant: {message.Text}");
        }
    }
    Console.WriteLine();
}

Console.WriteLine();
Console.WriteLine($"[run] {successes}/{results.Count} agents succeeded");
// `using var sdk = ...` will dispose at the end of Main, which flushes
// pending telemetry per the distro's contract.
return 0;

// ---------------------------------------------------------------------------
// Processor that stamps every span with test.agent / test.runId / test.protocol.
// ---------------------------------------------------------------------------
sealed class TestAgentProcessor(string agentName, string runId) : BaseProcessor<Activity>
{
    private static readonly AsyncLocal<string?> _protocol = new();

    public static void SetProtocol(string protocol) => _protocol.Value = protocol;

    public override void OnStart(Activity data)
    {
        data.SetTag("test.agent", agentName);
        data.SetTag("test.runId", runId);
        if (_protocol.Value is { } protocol)
            data.SetTag("test.protocol", protocol);
    }
}

// ---------------------------------------------------------------------------
// Weather plugin - exposes the weather tool as a static method for MAF
// ---------------------------------------------------------------------------
static class WeatherPlugin
{
    [Description("Gets the current weather for a given location.")]
    public static string GetCurrentWeather(
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
        string unitLabel = unit == "celsius" ? "\u00B0C" : "\u00B0F";

        Console.WriteLine($"[Tool] get_current_weather(\"{location}\", \"{unit}\")");

        return JsonSerializer.Serialize(new
        {
            location,
            temperature = $"{temp}{unitLabel}",
            condition = data.Condition
        });
    }
}
