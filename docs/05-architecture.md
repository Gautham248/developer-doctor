# Architecture

This doc explains how Developer Doctor is put together internally — useful
if you're contributing to the core project, writing a plugin, or just
curious how the pieces fit.

## Guiding principle: plugin-first, always

The core of Developer Doctor has **zero hardcoded knowledge** of what
Docker, Git, or any other specific tool is or how it works. Every
diagnostic — including the built-in ones — is implemented as a plugin
behind the exact same interface a third-party plugin author would use. The
core's only job is to discover plugins, run them, aggregate their scores,
and render the results.

```
Plugin → PluginResult → Health Scoring → Renderer
```

## Package layout

```
doctor/
├── cli.py                 # Typer app: command definitions and orchestration only
├── models.py               # Pydantic models: Status, Finding, PluginResult, Report
├── registry.py               # Assembles built-in + discovered plugins, applies config
├── discovery.py                # User-plugin and entry-point plugin loading
├── config.py                     # doctor.toml loading (DoctorConfig, PluginsConfig)
├── scoring.py                      # Health score aggregation, CI-critical-failure check
├── report.py                        # Rich terminal rendering (report, diff, trends)
├── baseline.py                       # Baseline save/load/diff
├── snapshot.py                        # Historical snapshot save/load/diff-target-parsing
├── trend.py                            # Multi-point trend computation
├── capabilities.py                      # Capability enum + CapabilityError
├── plugins/
│   ├── base.py                            # DoctorPlugin abstract base class
│   ├── system.py, cpu.py, memory.py, ...   # the 10 built-in plugins
├── services/
│   ├── base.py                              # BaseService contract
│   ├── process_service.py                    # shared psutil sampling logic
│   ├── git_service.py                          # shared GitPython/subprocess logic
│   ├── docker_service.py                         # shared docker CLI logic
│   └── battery_service.py                         # shared battery/system_profiler logic
├── formatters/
│   ├── json_formatter.py, yaml_formatter.py, html_formatter.py
├── sdk/
│   ├── testing.py                                  # PluginTestHarness
│   ├── scaffold.py                                   # `doctor plugin create`
│   ├── lint.py, package.py, publish.py                # `doctor plugin lint/package/publish`
└── utils/
    └── state.py                                        # Generic local JSON state persistence
```

---

## The plugin contract

Every plugin — built-in or third-party — is a subclass of `DoctorPlugin`:

```python
class DoctorPlugin(ABC):
    name: str
    description: str
    capabilities: list[Capability] = []

    def is_supported(self) -> bool:
        """Return False to skip this plugin on the current platform.
        Default: supported everywhere."""
        return True

    @abstractmethod
    def run(self) -> PluginResult:
        """Execute the diagnostic. Must never raise — catch your own
        exceptions and return a FAIL PluginResult instead."""
        ...
```

This is the **entire** interface the core knows about. It has no knowledge
of what any given plugin's `run()` actually does internally.

### `PluginResult`

Every `run()` call returns a `PluginResult` — a structured, Pydantic model
so it's trivially serializable to JSON/YAML/HTML without any per-format
plugin code:

```python
class PluginResult(BaseModel):
    plugin_name: str
    status: Status                    # PASS / WARN / FAIL / INFO
    score_delta: int = 0                # points to subtract from 100
    findings: list[Finding] = []          # human-readable observations
    recommendations: list[str] = []         # actionable next steps
    metadata: dict[str, Any] = {}             # machine-readable data (used by diff/trend)
    data: dict[str, Any] | None = None          # reserved for future renderer-specific payloads
```

### The "never crash" contract

Plugins are individually responsible for catching their own exceptions.
Every built-in plugin wraps its entire `run()` body in a broad
`try/except Exception`, returning a `FAIL` `PluginResult` with the error
message as detail rather than letting an exception propagate. A single
misbehaving plugin (built-in or third-party) must never take down the
whole `doctor` process.

---

## Health scoring

Scoring is deliberately dumb — the core has no opinion about *why* points
were deducted, it only sums:

```python
def compute_health_score(results: list[PluginResult]) -> int:
    total_deductions = sum(r.score_delta for r in results)
    return max(0, 100 - total_deductions)
```

Score starts at 100. It's floored at 0 even if deductions overshoot.
`has_critical_failures()` (used by `--ci`) is a separate, equally simple
check: `any(r.status == Status.FAIL for r in results)`.

---

## Plugin discovery

Three tiers, assembled in `registry.discover_all_plugins()`:

1. **Built-in** — the 10 plugins shipped with the core, always loaded
   explicitly (not scanned — first-party plugins are curated).
2. **User** — any `.py` file in `~/.config/doctor/plugins/` (excluding
   files starting with `_`) is dynamically imported, and every
   `DoctorPlugin` subclass found is instantiated.
3. **Third-party (entry points)** — any package registered under the
   `doctor.plugins` Python entry-point group is loaded via
   `importlib.metadata.entry_points()`. This is what makes
   `pip install doctor-plugin-kubernetes` (hypothetically) "just work"
   with zero further configuration.

**Failure isolation**: a broken user plugin file, or an entry point that
fails to load, is caught individually and reported as a warning string —
it never prevents the rest of discovery from succeeding.

**Name collisions**: built-in plugins always win. If a user or third-party
plugin declares the same `name` as a built-in, the built-in is kept and
the collision is reported as a warning — a plugin can never silently
shadow a core diagnostic.

After discovery, `config.py`'s `enabled`/`disabled` lists are applied, then
each remaining plugin's `is_supported()` is checked.

---

## Capability system and shared services

As the ecosystem of plugins grows, unrestricted system access per plugin
doesn't scale safely. The capability system asks "what has this plugin
declared it needs?" rather than "what can this plugin do?"

```python
class Capability(str, Enum):
    PROCESS_INSPECTION = "process_inspection"
    FILESYSTEM_READ = "filesystem_read"
    FILESYSTEM_WRITE = "filesystem_write"
    NETWORK_SOCKETS = "network_sockets"
    PACKAGE_MANAGERS = "package_managers"
    SHELL_COMMANDS = "shell_commands"
    SYSTEM_PROFILER = "system_profiler"
    BATTERY_INFORMATION = "battery_information"
    DOCKER_DAEMON_ACCESS = "docker_daemon_access"
    KUBERNETES_API_ACCESS = "kubernetes_api_access"
    GIT_REPOSITORY_ACCESS = "git_repository_access"
```

A plugin declares what it needs:

```python
class MyPlugin(DoctorPlugin):
    capabilities = [Capability.SHELL_COMMANDS]
```

...and requests access to a shared service via `self.use_service(...)`,
which enforces declaration at runtime:

```python
def use_service(self, service_class: type[ServiceT]) -> ServiceT:
    required = service_class.required_capability
    if required not in self.capabilities:
        raise CapabilityError(...)
    return service_class()
```

### Honest scope of enforcement — read this carefully

Enforcement happens **only at the shared-services boundary**. Five plugins
(`cpu`, `ai_ide`, `git`, `docker`, `battery`) route all of their real
system access through a shared service
(`ProcessService`/`GitService`/`DockerService`/`BatteryService`) and are
therefore fully covered by capability enforcement.

The other five (`system`, `memory`, `disk`, `node`, `python`) declare
capabilities as self-attested metadata but still call `psutil`/`subprocess`
directly, because their checks are simple enough (a single `psutil` call,
or a filesystem read) that routing them through a dedicated service would
be pure ceremony with no real duplication to eliminate. **This is a stated
design choice, not an oversight** — genuine sandboxing of arbitrary system
calls (running third-party plugins in isolated subprocesses with timeouts)
is explicitly deferred future work, not something the current capability
system claims to provide.

### Shared services

| Service | Required capability | Wraps |
|---|---|---|
| `ProcessService` | `PROCESS_INSPECTION` | The `psutil` prime-then-sample pattern for CPU%/RAM sampling — used by both `cpu` and `ai_ide`, which is the actual duplication this system exists to eliminate |
| `GitService` | `GIT_REPOSITORY_ACCESS` | GitPython config/repo access, SSH config parsing, `git ls-remote` |
| `DockerService` | `DOCKER_DAEMON_ACCESS` | `docker info`/`docker stats` shelling and parsing |
| `BatteryService` | `BATTERY_INFORMATION` | `psutil.sensors_battery()` and `system_profiler` parsing |

---

## Output formats / rendering pipeline

```
[PluginResult, ...] → Report (score + timestamp + results) → one of:
    - report.py's render_report()      (Rich terminal, default)
    - formatters/json_formatter.py       (render_json)
    - formatters/yaml_formatter.py         (render_yaml)
    - formatters/html_formatter.py           (render_html)
```

All four renderers consume the exact same `Report` object — no renderer has
any plugin-specific logic. The HTML renderer is a single self-contained
file (no external CSS/JS dependencies) with all plugin-supplied strings
HTML-escaped, since process names, git remotes, and error messages
originate from system state and are treated as untrusted input even
outside a multi-user web context.

`render_diff()` (used by both `doctor baseline compare` and `doctor diff`)
and `render_trends()` (used by `doctor trend`) are separate renderers that
operate on `PluginDiff`/`MetricTrend` objects rather than a raw `Report` —
see [`baseline.py`](../../doctor/baseline.py) and
[`trend.py`](../../doctor/trend.py) for those data shapes.

---

## State persistence

`doctor/utils/state.py` provides the one general-purpose local persistence
mechanism the project uses, backed by `platformdirs` (so it respects OS
conventions for where application data belongs):

```python
def load_json(key: str) -> Any | None: ...
def save_json(key: str, data: Any) -> None: ...
```

Both are best-effort: a write failure is silently swallowed (losing
historical state should never crash a diagnostic run), and a missing or
corrupted read returns `None` rather than raising.

Three features build on this:
- `ai_ide`'s cross-run sustained-CPU tracking (typed convenience wrappers
  `load_state`/`save_state` for simple string-keyed data).
- `baseline.py` (`save_baseline`/`load_baseline`, storing a full `Report`).
- `snapshot.py` (`save_snapshot`/`load_snapshots`, storing a growing,
  capped list of timestamped `Report`s).

---

## Configuration flow

```
doctor.toml (upward search from cwd)
    → config.load_config() → DoctorConfig (pydantic)
        → registry.discover_all_plugins(config)
            → applies enabled/disabled lists
            → passes thresholds dicts into supporting plugins' __init__
```

A missing or malformed `doctor.toml` never raises — `load_config()` falls
back to `DoctorConfig()` defaults, which is functionally identical to
having no config at all.

---

## Design principles this codebase actually follows

- **Fast**: the sampling-based plugins (`cpu`, `ai_ide`) use a single
  ~0.5 second sample window, shared across both system-wide and
  per-process reads, rather than paying that cost multiple times.
- **Deterministic-ish**: given the same system state, output is
  consistent — though live system metrics obviously vary run to run by
  nature, which is expected and correct, not a determinism bug.
- **Least privilege**: no plugin requires administrator/root privileges.
  The SMART-disk-data and large-directory-scan features were explicitly
  *not* built specifically because they'd require privileges this project
  doesn't want to ask for by default.
- **Fails safe, never crashes**: enforced at the plugin level
  (`try/except` in every `run()`), the discovery level (broken plugins are
  isolated, not fatal), and the config level (malformed config falls back
  to defaults).
- **No telemetry by default**: nothing in this codebase phones home. Any
  future opt-in analytics/benchmarking would need to be explicitly
  opt-in, never default-on.
