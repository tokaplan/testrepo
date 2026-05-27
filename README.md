testrepo
========

This repository contains sample weather-agent implementations used to validate
OpenTelemetry GenAI semantic-convention compliance across multiple agent
stacks.

## 📌 Canonical implementations

All compliance work is scoped to **exactly four** implementations. See
[`CANONICAL-AGENTS.md`](CANONICAL-AGENTS.md) for the canonical disk paths,
shared-resource details, row → folder mapping, and the pre-flight checklist
that must hold before any validation run.

The compliance matrix produced from those four implementations lives in
[`data/agent-telemetry-compliance.md`](data/agent-telemetry-compliance.md).

Other top-level folders (e.g. `WeatherChat\`, `WeatherChatMAF\`,
`LangChainPython\`, `LangChainNodeJs\`, `TeamsAgent\`) are legacy / unrelated
and **must not** be used when refreshing the matrix.
