# Plugin Development Guide

This is the complete guide to writing your own Developer Doctor plugin —
whether a small personal check you keep in `~/.config/doctor/plugins/`, or
a real, publishable third-party package.

## Two ways to add a plugin

| Approach | Best for | Discovery mechanism |
|---|---|---|
| **User plugin** | Personal checks specific to your machine/workflow | Any `.py` file dropped into `~/.config/doctor/plugins/` |
| **Third-party package** | Checks you want to share, or install via `pip` | Python entry points (`doctor.plugins` group) |

Both are loaded through the exact same underlying mechanism and are
subject to the exact same contract — the difference is purely about
distribution, not capability.

---

## Quick path: a user plugin in 5 minutes

Create `~/.config/doctor/plugins/hello.py`:

```python
from doctor.models import Finding, PluginResult, Status
from doctor.plugins.base import DoctorPlugin


class HelloPlugin(DoctorPlugin):
    name = "hello"
    description = "A trivial example plugin."

    def run(self) -> PluginResult:
        return PluginResult(
            plugin_name=self.name,
            status=Status.INFO,
            findings=[Finding(summary="Hello from a user plugin!")],
        )
```

Run `doctor` — your plugin appears in the report automatically, with **zero
changes to the core project**. That's the whole point of the plugin-first
architecture: this is not a special case, it's the same path every
built-in plugin's logic (conceptually) goes through.

Filenames starting with `_` are skipped, so you can keep shared helper
modules alongside your plugin files without them being mistaken for
plugins themselves.

---

## The plugin contract, in detail

```python
from doctor.capabilities import Capability
from doctor.models import Finding, PluginResult, Status
from doctor.plugins.base import DoctorPlugin


class MyPlugin(DoctorPlugin):
    name = "my_plugin"                     # unique, lowercase, used everywhere (config, CLI, output)
    description = "What this plugin checks."
    capabilities: list[Capability] = []       # see "Capabilities" below

    def is_supported(self) -> bool:
        """Return False to skip this plugin — e.g. required tool not
        installed, or platform-specific. Default: True (always runs)."""
        return True

    def run(self) -> PluginResult:
        """MUST NOT raise. Catch your own exceptions internally."""
        try:
            # ... your diagnostic logic ...
            return PluginResult(
                plugin_name=self.name,
                status=Status.PASS,
                findings=[Finding(summary="Everything looks fine.")],
            )
        except Exception as e:
            return PluginResult(
                plugin_name=self.name,
                status=Status.FAIL,
                findings=[Finding(summary="Could not run diagnostic", detail=str(e))],
            )
```

### `Status` values

| Status | Meaning | Affects `--ci` exit code? | Affects health score? |
|---|---|---|---|
| `PASS` | Everything checked out | No | No |
| `INFO` | Purely informational, no judgment | No | No |
| `WARN` | Worth a human's attention, not urgent | No | Typically yes (your choice of `score_delta`) |
| `FAIL` | Something is genuinely broken | **Yes** | Typically yes |

### `score_delta`

An integer number of points to subtract from the starting score of 100.
There's no enforced convention, but the built-in plugins generally use
`5` for `WARN` and `15` for `FAIL` — following that convention keeps your
plugin's severity roughly comparable to the built-ins', but nothing
enforces it.

### `findings` vs `recommendations`

- `findings` — what you observed. Should read naturally as a list of
  facts, even out of context (they're rendered as bullet points).
- `recommendations` — what the person should actually *do* about it. Only
  include these when `status` isn't `PASS`/`INFO` — a recommendation
  attached to a passing check is confusing.

### `metadata`

A flat `dict[str, Any]` for machine-readable data. **Keep numeric fields
flat** (not nested) if you want them to participate in
`doctor trend`/`doctor diff` — both currently only inspect top-level
numeric values in `metadata`, not nested structures. This is a known,
documented gap (see [`04-plugins-reference.md`](04-plugins-reference.md)'s
note on the `ai_ide` plugin, which has this exact limitation).

---

## Capabilities and shared services

If your plugin needs to inspect processes, read Git state, talk to Docker,
or read battery info, check first whether an existing shared service
already covers it — using one gives you tested, reusable logic for free
instead of hand-rolling `subprocess`/`psutil` calls.

```python
from doctor.capabilities import Capability
from doctor.services.process_service import ProcessService

class MyPlugin(DoctorPlugin):
    capabilities = [Capability.PROCESS_INSPECTION]

    def run(self) -> PluginResult:
        service = self.use_service(ProcessService)
        top_procs, cpu_percent, load_avg = service.sample_system_and_processes()
        ...
```

Calling `self.use_service(SomeService)` **without** declaring the matching
capability in `self.capabilities` raises `CapabilityError` — this is
enforced, not just documented convention, for the four services that
exist today (see table below). Declaring a capability you don't actually
use is harmless; the reverse (using a service without declaring it) is a
hard error.

| If you need to... | Use | Declare |
|---|---|---|
| Sample CPU%/RAM for processes | `ProcessService` | `Capability.PROCESS_INSPECTION` |
| Read Git config, repo state, remote reachability | `GitService` | `Capability.GIT_REPOSITORY_ACCESS` |
| Query the Docker daemon | `DockerService` | `Capability.DOCKER_DAEMON_ACCESS` |
| Read battery charge/health | `BatteryService` | `Capability.BATTERY_INFORMATION` |

If none of these fit, calling `subprocess`/`psutil`/the filesystem directly
is fine (that's what most built-in plugins still do) — just declare the
closest matching `Capability` from the enum as accurate, honest metadata
about what your plugin touches, even though it won't be enforced.

---

## Testing your plugin

Use `PluginTestHarness` — it runs your plugin exactly the way the real CLI
does, through the public `run()`/`is_supported()` methods, so your tests
exercise the same contract the core enforces.

```python
from doctor.sdk.testing import PluginTestHarness
from my_plugin import MyPlugin


def test_plugin_runs_without_raising():
    harness = PluginTestHarness()
    result = harness.run(MyPlugin())
    assert result.status in (Status.PASS, Status.WARN, Status.FAIL, Status.INFO)
```

Important: the harness **deliberately does not catch exceptions** from
`run()`/`is_supported()`. If your plugin violates the "never raise"
contract, the test should fail loudly — that's a bug in your plugin, not
something the harness should quietly absorb.

---

## Scaffolding a real, publishable plugin

```bash
doctor plugin create postgres
```

This generates a complete, standalone package:

```
doctor-plugin-postgres/
├── doctor_plugin_postgres/
│   ├── __init__.py
│   └── plugin.py                # a working sample plugin, ready to edit
├── tests/
│   └── test_plugin.py             # uses PluginTestHarness already
├── .github/workflows/ci.yml         # a working GitHub Actions CI workflow
├── pyproject.toml                     # entry point already wired up
├── README.md
└── LICENSE                              # MIT, edit as needed
```

The generated `pyproject.toml` already registers the entry point correctly:

```toml
[project.entry-points."doctor.plugins"]
postgres = "doctor_plugin_postgres.plugin:PostgresPlugin"
```

This is what makes discovery automatic once the package is installed in
the same environment as `developer-doctor` — no further registration step.

### Important honest note

The generated `pyproject.toml` depends on `developer-doctor`, which **is
not yet published to PyPI**. Until it is, install both packages from local
checkouts in the same environment:

```bash
uv pip install -e /path/to/developer-doctor
uv pip install -e .
```

The generated README already states this explicitly.

---

## Validating, linting, packaging, publishing

```bash
# Load the plugin the same way the real CLI would, and sanity-check it —
# reports capabilities, is_supported(), and the result of run(), catching
# and clearly reporting any exception your plugin raises.
doctor plugin validate doctor_plugin_postgres/plugin.py

# Run ruff + mypy. A tool that isn't installed is skipped, not failed.
doctor plugin lint doctor-plugin-postgres/

# Build a wheel + sdist via `uv build`.
doctor plugin package doctor-plugin-postgres/

# Validate (twine check, local only) and, with explicit confirmation,
# upload. Defaults to testpypi; pass --repository pypi for the real index.
doctor plugin publish doctor-plugin-postgres/
```

`publish` is the one command in the entire SDK that performs a real,
irreversible external action. It always runs `twine check` first (fully
local), and never uploads without either an interactive "yes" or an
explicit `--yes` flag — there's no way to trigger a real upload by
accident. See [`02-cli-reference.md`](02-cli-reference.md#doctor-plugin-publish-path---repository-repo---yes)
for full flag details.

---

## Design rules for plugins (worth following even though not all are enforced)

- **Never require administrator/root privileges.** If your check needs
  elevated access, it should degrade gracefully instead (report what it
  can, note what it couldn't check) rather than demanding `sudo`.
- **Avoid network access unless strictly necessary.** The only built-in
  plugin doing this today is `git` (remote reachability), and it's
  explicitly documented as an exception, not the norm.
- **Be independent of other plugins.** Don't assume another plugin ran
  first, or read another plugin's `metadata`.
- **Fail gracefully, always.** A plugin that raises breaks the "never
  crash the process" guarantee the whole project is built around.
- **Declare platform support via `is_supported()`** rather than silently
  returning an empty/meaningless result on unsupported platforms.

---

## Common mistakes `doctor plugin validate` will actually catch

- A `run()` (or `is_supported()`) that raises an uncaught exception —
  reported clearly, with guidance to catch it and return a `FAIL`
  `PluginResult` instead.
- A file that defines no `DoctorPlugin` subclass at all.
- A file that fails to import (syntax error, missing dependency) —
  reported as a load error rather than a Python traceback.

What it does **not** currently catch: `mypy`/`ruff` issues (use
`doctor plugin lint` for that), or logical correctness of your diagnostic
(only you can verify that your thresholds and messaging actually make
sense).
