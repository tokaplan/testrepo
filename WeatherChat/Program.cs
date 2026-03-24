using System.ClientModel;
using Azure.AI.OpenAI;
using Azure.Monitor.OpenTelemetry.Exporter;
using OpenAI.Chat;
using OpenTelemetry;
using OpenTelemetry.Metrics;
using OpenTelemetry.Trace;

// ---------------------------------------------------------------------------
// WeatherChat - a simple console app that asks an Azure OpenAI model about
// the weather, with OTEL telemetry exported to Application Insights.
// ---------------------------------------------------------------------------

const string endpoint = "https://alkap-mc9jji6o-eastus2.cognitiveservices.azure.com";
const string deploymentName = "my-chat-deployment-1";
const string appInsightsConnectionString =
    "InstrumentationKey=cfbc4eae-b34d-47e1-91b8-6bb19d315373;" +
    "IngestionEndpoint=https://eastus-8.in.applicationinsights.azure.com/;" +
    "LiveEndpoint=https://eastus.livediagnostics.monitor.azure.com/;" +
    "ApplicationId=9ebafd11-a230-44bb-bc57-4cdcc42646a8";

// Opt in to the experimental OpenAI/Azure.AI.OpenAI telemetry
AppContext.SetSwitch("OpenAI.Experimental.EnableOpenTelemetry", true);

// ----- Configure OpenTelemetry tracing & metrics ---------------------------
// The Azure.AI.OpenAI SDK emits traces under "OpenAI.*" activity sources
// and metrics under "OpenAI.*" meters when the experimental switch is on.

using var tracerProvider = Sdk.CreateTracerProviderBuilder()
    .AddSource("OpenAI.*")
    .AddHttpClientInstrumentation()
    .AddAzureMonitorTraceExporter(o => o.ConnectionString = appInsightsConnectionString)
    .Build();

using var meterProvider = Sdk.CreateMeterProviderBuilder()
    .AddMeter("OpenAI.*")
    .AddRuntimeInstrumentation()
    .AddHttpClientInstrumentation()
    .AddAzureMonitorMetricExporter(o => o.ConnectionString = appInsightsConnectionString)
    .Build();

// ----- Prompt for API key --------------------------------------------------
Console.Write("Enter your Azure OpenAI API key: ");
string? apiKey = Console.ReadLine()?.Trim();

if (string.IsNullOrWhiteSpace(apiKey))
{
    Console.Error.WriteLine("Error: An API key is required.");
    return 1;
}

// ----- Create client & send request ----------------------------------------
AzureOpenAIClient azureClient = new(
    new Uri(endpoint),
    new ApiKeyCredential(apiKey));

ChatClient chatClient = azureClient.GetChatClient(deploymentName);

string userPrompt = "How do you call a person who wants to see before they can believe?";

Console.WriteLine();
Console.WriteLine($"You: {userPrompt}");
Console.WriteLine();

try
{
    ChatCompletion completion = await chatClient.CompleteChatAsync(
        [
            new SystemChatMessage("You are a helpful weather assistant."),
            new UserChatMessage(userPrompt)
        ]);

    Console.WriteLine($"Assistant: {completion.Content[0].Text}");
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
