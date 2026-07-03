# Developer Doctor — Documentation

Developer Doctor (`doctor`) is a plugin-driven CLI that diagnoses developer
workstations and produces a concise, actionable health report — the
equivalent of `brew doctor` or `flutter doctor`, but for your entire
development environment.

This folder contains the complete documentation set for the project as it
stands today. Start here, then jump to whichever doc matches what you're
trying to do.

## Documentation Index

| Doc | What it covers |
|---|---|
| [`docs/01-installation.md`](docs/01-installation.md) | Getting `doctor` running locally, both as a contributor and as an end user |
| [`docs/02-cli-reference.md`](docs/02-cli-reference.md) | Every command, flag, and output mode — the complete user-facing surface |
| [`docs/03-configuration.md`](docs/03-configuration.md) | `doctor.toml` — enabling/disabling plugins, tuning thresholds |
| [`docs/04-plugins-reference.md`](docs/04-plugins-reference.md) | What each of the 10 built-in plugins checks, how, and what triggers WARN/FAIL |
| [`docs/05-architecture.md`](docs/05-architecture.md) | How the codebase is put together: plugin system, capabilities, shared services, scoring, rendering |
| [`docs/06-plugin-development.md`](docs/06-plugin-development.md) | Writing, testing, scaffolding, linting, packaging, and publishing your own plugin |
| [`docs/07-publishing.md`](docs/07-publishing.md) | Releasing Developer Doctor itself — PyPI, GitHub Releases, Homebrew |
| [`docs/08-troubleshooting-faq.md`](docs/08-troubleshooting-faq.md) | Common issues and their fixes |

## 30-second overview

```bash
doctor                # run all diagnostics, human-readable report
doctor --json          # machine-readable output
doctor --ci             # exit non-zero on any FAIL, for CI pipelines
doctor snapshot          # record a point-in-time snapshot for later comparison
doctor trend               # see how things have changed across snapshots
doctor baseline create      # capture a "known good" state
doctor baseline compare      # compare current state against it
doctor plugin create <name>   # scaffold a new third-party plugin
```

## Project status at a glance

- **10 built-in plugins**: System, CPU, Memory, Battery, Disk, Git, Docker,
  Node, Python, AI IDE diagnostics.
- **Three output formats**: Rich terminal (default), JSON, YAML, and HTML.
- **Real plugin discovery**: built-in, user-local (`~/.config/doctor/plugins/`),
  and third-party (Python entry points) — the same discovery path Homebrew's
  and pytest's plugin ecosystems use.
- **Config-driven**: `doctor.toml` per-project, no config required to get
  started.
- **CI-ready**: `--ci` flag with meaningful, documented exit-code semantics.
- **Capability system**: plugins declare what system access they need;
  a shared services layer (`ProcessService`, `GitService`, `DockerService`,
  `BatteryService`) mediates the riskiest operations.
- **Historical tracking**: baselines (two-point comparison) and snapshots +
  trend analysis (multi-point, requires ≥3 data points).
- **Full plugin author SDK**: scaffold → validate → lint → package → publish.

See [`docs/05-architecture.md`](docs/05-architecture.md) for the full picture
of how these pieces fit together.
