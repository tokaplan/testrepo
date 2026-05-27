# AGENTS.md — instructions for AI assistants working in this repo

> **READ THIS FIRST.** This file tells any AI assistant (GitHub Copilot, Codex,
> Claude, etc.) which agent folders are the canonical implementations and
> which folders must be ignored. The naming in this repo is genuinely
> confusing — there are seven legacy folders with similar names. Past AI
> sessions have repeatedly run the wrong folder. Follow the rules below to
> avoid that mistake.

## 🟢 The 4 canonical agent implementations

**Every compliance, telemetry, and "the 4 agents" task in this repo refers to
exactly these four folders — and nothing else.**

| # | Implementation | Canonical path (use this) | Entry point |
|:-:|---|---|---|
| 1 | MAF .NET | `MAF with Microsoft OTEL distro\DotNet\` | `Program.cs` |
| 2 | MAF Python | `MAF with Microsoft OTEL distro\Python\` | `main.py` |
| 3 | LangChain Python | `LangChain with Microsoft OTEL distro\Python\` | `main.py` |
| 4 | LangChain NodeJs | `LangChain with Microsoft OTEL distro\NodeJs\` | `main.js` |

Note: the canonical folder names contain spaces (`MAF with Microsoft OTEL
distro`, `LangChain with Microsoft OTEL distro`). On Windows PowerShell, quote
the path: `cd "C:\Git\testrepo\LangChain with Microsoft OTEL distro\NodeJs"`.

Each canonical folder's `README.md` starts with a `> ✅ CANONICAL` banner.
**If the README does not have that banner, you are in the wrong folder.**

## 🔴 Legacy folders — never use these for matrix / compliance work

The names below are extremely easy to confuse with the canonical ones. Each
of these folders contains a `README.md` whose first line is a
`> ⛔ LEGACY` banner. Treat that banner as a hard stop.

| Legacy folder | Confused with | Use instead |
|---|---|---|
| `LangChainNodeJs\` | LangChain NodeJs canonical | `LangChain with Microsoft OTEL distro\NodeJs\` |
| `LangChainPython\` | LangChain Python canonical | `LangChain with Microsoft OTEL distro\Python\` |
| `WeatherChat\` | (early baseline) | none |
| `WeatherChatMAF\` | MAF .NET canonical | `MAF with Microsoft OTEL distro\DotNet\` |
| `WeatherChatMAFPython\` | MAF Python canonical | `MAF with Microsoft OTEL distro\Python\` |
| `WeatherChatPython\` | LangChain Python canonical | `LangChain with Microsoft OTEL distro\Python\` |
| `TeamsAgent\` | (unrelated Teams project) | n/a |

## Pre-flight checklist (do this before every validation run)

1. **Canonical path?** Your `cd` / `Set-Location` target must start with
   `MAF with Microsoft OTEL distro\…` or `LangChain with Microsoft OTEL distro\…`.
   If it does not, you are running a legacy agent — STOP.
2. **Canonical banner?** Open the target folder's `README.md` and confirm the
   first line is `> ✅ CANONICAL`. If it isn't, STOP.
3. **Cloud-role name?** After the run, the App Insights cloud-role name on the
   spans must be one of:
   - `WeatherChatMAF-MS-Distro` (MAF .NET)
   - `WeatherChatMAFPython-MS-Distro` (MAF Python)
   - `WeatherChatLangChain-MS-Distro` (LangChain Python)
   - `LangChainNodeJs-MS-Distro` (LangChain NodeJs)
4. **Run-ID convention?** Pass an explicit `test.runId`
   (e.g. `verify-mafnet-<HHmmss>`) so the run is queryable end-to-end.

If any of these fails, the validation result is **not** comparable to the
existing matrix rows and must not be committed.

## Authoritative references

- `CANONICAL-AGENTS.md` — the single source of truth for canonical paths,
  shared resources, and row → folder mapping.
- `data/agent-telemetry-compliance.md` — the compliance matrix produced by
  the four canonical agents.
- `README.md` — repository entry point with pointer to the above.
