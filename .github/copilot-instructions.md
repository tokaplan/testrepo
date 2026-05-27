- @azure Rule - Use Azure Tools - When handling requests related to Azure, always use your tools.
- @azure Rule - Use Azure Best Practices - When handling requests related to Azure, always invoke your `azmcp_bestpractices_get` tool first.
- @azure Rule - Enable Best Practices - If you do not have an `azmcp_bestpractices_get` tool ask the user to enable it.

## Canonical agent implementations (critical)

Whenever the user mentions "the 4 agents", "our agents", "the weather agents",
the compliance matrix, telemetry validation, or anything similar, those terms
refer to **exactly** the four implementations listed in
[`/AGENTS.md`](../AGENTS.md) and [`/CANONICAL-AGENTS.md`](../CANONICAL-AGENTS.md):

1. **MAF .NET** → `MAF with Microsoft OTEL distro\DotNet\`
2. **MAF Python** → `MAF with Microsoft OTEL distro\Python\`
3. **LangChain Python** → `LangChain with Microsoft OTEL distro\Python\`
4. **LangChain NodeJs** → `LangChain with Microsoft OTEL distro\NodeJs\`

The following look-alike folders are **legacy and must never be used** for
validation, matrix updates, or runs: `LangChainNodeJs\`, `LangChainPython\`,
`WeatherChat\`, `WeatherChatMAF\`, `WeatherChatMAFPython\`,
`WeatherChatPython\`, `TeamsAgent\`. Each legacy folder's `README.md` starts
with a `> ⛔ LEGACY` banner; each canonical folder's `README.md` starts with
`> ✅ CANONICAL`. Confirm the banner before running anything.

