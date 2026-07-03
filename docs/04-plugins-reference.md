# Built-in Plugins Reference

Developer Doctor ships with 10 built-in plugins. This doc covers what each
one checks, how it detects problems, what triggers `WARN`/`FAIL`, and which
thresholds (if any) are configurable via `doctor.toml`.

For the general shape every plugin follows, see
[`05-architecture.md`](05-architecture.md#the-plugin-contract).

---

## `system`

**Status**: always `INFO` — this plugin never fails, it's purely
informational.

**Reports**: OS name and release, CPU architecture, total RAM, system
uptime.

**Configurable thresholds**: none.

---

## `cpu`

**Detects**: overall CPU usage and runaway individual processes.

**How**: samples system-wide CPU% and per-process CPU% using a
prime-then-sample technique (a first read is always primed and discarded,
since `psutil` requires a baseline before it can compute a meaningful
delta), then reports the top 3 processes by CPU usage above a 1% noise
floor.

**Thresholds** (`[thresholds.cpu]`):

| Key | Default | Meaning |
|---|---|---|
| `warn_percent` | `70.0` | Overall CPU% that triggers `WARN` |
| `fail_percent` | `90.0` | Overall CPU% that triggers `FAIL` |
| `runaway_process_percent` | `80.0` | Per-process CPU% that flags that specific process as a recommendation, even if overall usage is fine |

---

## `memory`

**Detects**: RAM usage and swap pressure.

**How**: reads system virtual memory and swap statistics directly via
`psutil`.

**Thresholds** (`[thresholds.memory]`):

| Key | Default | Meaning |
|---|---|---|
| `warn_percent` | `80.0` | RAM usage % that triggers `WARN` |
| `fail_percent` | `95.0` | RAM usage % that triggers `FAIL` |
| `warn_swap_gb` | `2.0` | Swap usage (GB) that triggers `WARN` |
| `fail_swap_gb` | `8.0` | Swap usage (GB) that triggers `FAIL` |

Heavy swap usage is treated as a stronger signal than RAM% alone — a
machine that's swapping is actively paging to disk, which feels
significantly slower than RAM% alone would suggest.

---

## `battery`

**Platform note**: only runs on machines that report a battery (desktops
are automatically skipped via `is_supported()`).

**Detects**: charge level, plugged-in state, and — **macOS only** — cycle
count and battery health (max capacity as a percentage of design capacity).

**How**: charge/plugged state come from `psutil.sensors_battery()`
(cross-platform). Cycle count and health are parsed from
`system_profiler SPPowerDataType`, which only exists on macOS. On other
platforms, or if parsing fails for any reason, the plugin degrades
gracefully to charge%/plugged-state only — this is **not** treated as an
error.

**Thresholds** (`[thresholds.battery]`, macOS only — these have no effect
without health data):

| Key | Default | Meaning |
|---|---|---|
| `warn_health_percent` | `80.0` | Battery health % (of design capacity) at or below which `WARN` triggers |
| `fail_health_percent` | `60.0` | Battery health % at or below which `FAIL` triggers |
| `warn_cycle_count` | `800` | Cycle count at or above which `WARN` triggers |
| `fail_cycle_count` | `1000` | Cycle count at or above which `FAIL` triggers |

---

## `disk`

**Detects**: capacity usage of the primary volume (`/`).

**How**: `psutil.disk_usage("/")`.

**Explicitly out of scope for this plugin** (documented gaps, not
oversights):
- SMART disk-health data — would require the `smartctl` binary, which most
  users don't have installed, and typically needs elevated privileges,
  conflicting with the project's least-privilege stance.
- "Large directories" scanning — needs a scoped, safe, time-bounded
  traversal strategy that deserves its own design pass.

**Thresholds** (`[thresholds.disk]`):

| Key | Default | Meaning |
|---|---|---|
| `warn_percent` | `85.0` | Disk usage % that triggers `WARN` |
| `fail_percent` | `95.0` | Disk usage % that triggers `FAIL` |

---

## `git`

**Platform note**: skipped entirely if `git` isn't installed.

**Detects**:
- Whether a global Git identity (`user.name`/`user.email`) is configured.
- Whether the current directory is inside a Git repository (walks upward
  like Git itself does).
- A repo-local identity override, if one exists (useful for catching
  accidental work/personal identity mismatches across repos).
- The configured `origin` remote URL.
- Whether your `~/.ssh/config` defines an alias for the remote's host that
  isn't being used — a real, common misconfiguration where you have an
  SSH alias set up (e.g. for using a different key per account) but the
  remote URL bypasses it.
- Remote reachability, via `git ls-remote` with a 5-second timeout.

**On network access**: this is the one built-in plugin that makes a
network call (checking remote reachability). This is a deliberate,
documented exception to the project's general "avoid network access unless
strictly necessary" stance — reachability is core to what makes Git
diagnostics useful. An unreachable remote produces `WARN`, not `FAIL`,
since "you're offline right now" isn't really an environment problem.

**Thresholds**: none configurable — the identity/remote checks are
inherently binary rather than threshold-based. Missing global identity is a
hardcoded `FAIL`; an unreachable remote is a hardcoded `WARN`.

---

## `docker`

**Platform note**: skipped entirely if the `docker` CLI isn't installed.

**Detects**: whether the Docker daemon is running, container count
(running vs. total), and aggregate memory usage across running containers.

**How**: shells out to `docker info --format '{{json .}}'` and
`docker stats --no-stream`, parsing Docker's human-readable memory strings
(e.g. `"512MiB"`, `"1.2GiB"`) into bytes.

Docker installed but the daemon not running is reported as `WARN`, not
`FAIL` — a stopped Docker Desktop is a common, low-severity state, not a
broken environment.

**Thresholds** (`[thresholds.docker]`):

| Key | Default | Meaning |
|---|---|---|
| `warn_container_memory_gb` | `8.0` | Total container RAM usage that triggers `WARN` |
| `fail_container_memory_gb` | `16.0` | Total container RAM usage that triggers `FAIL` |

---

## `node`

**Platform note**: skipped entirely if `node` isn't on `PATH`.

**Detects**:
- Active Node.js version.
- Which version manager controls the active `node` binary — `mise`, `nvm`,
  `volta`, `fnm`, Homebrew, or plain system install — inferred from the
  resolved binary path.
- The project's package manager (`npm`/`yarn`/`pnpm`/`bun`), inferred from
  lockfiles in the current directory.
- Whether **multiple** Node version managers appear to be installed at
  once (e.g. both `nvm` and `mise`), which is a real, common cause of "the
  wrong Node version got picked up" bugs depending on shell startup order.

**Known limitation, stated honestly**: version-manager detection is a path
substring heuristic, not a guarantee. Custom/nonstandard install locations
can cause a misdetection.

**Thresholds**: none — every check here is informational or binary
(manager conflict detected or not).

---

## `python`

**Detects**:
- The Python version currently running `doctor` itself.
- Whether an active virtualenv is in use, and if so, **what created it**
  (`uv`, `virtualenv`, or stdlib `venv`) — read from the venv's
  `pyvenv.cfg` marker file, not guessed from the path.
- Separately, what manages the **base interpreter** underneath any active
  venv (`mise`, `pyenv`, Homebrew, or system) — this is deliberately a
  distinct question from "what created the venv," since a venv layered on
  top of a mise-managed interpreter is a very common real-world setup that
  a naive "check `sys.executable`" approach would misreport as
  "system-managed."
- Whether the current directory looks like a Python project
  (`pyproject.toml`/`setup.py`/`requirements.txt` present) with no active
  virtualenv — flagged as `WARN`, since installing packages globally next
  to a real Python project risks cross-project version conflicts.
- Whether multiple Python version managers appear to be installed at once.

**Thresholds**: none — all checks here are informational or binary.

---

## `ai_ide`

This is the plugin closest to the project's core positioning statement
("why are language servers stuck?") — it correlates *processes* with
*known IDE naming patterns* and reasons about *sustained* behavior over
time, not just a single snapshot.

**Detects**: orphaned or runaway processes belonging to Antigravity,
VS Code, Cursor, Claude Code, or Gemini CLI.

**Confidence levels, stated explicitly**: Electron-based IDEs (Antigravity,
VS Code, Cursor) spawn distinctly-named helper processes, which makes
detection reliable. CLI-based agents (Claude Code, Gemini CLI) are matched
on much weaker substrings (`"claude"`, `"gemini"`) that could in principle
collide with unrelated process names — a documented lower-confidence match,
not a false claim of certainty.

**How sustained-usage detection works**: unlike every other built-in
plugin, `ai_ide` persists lightweight state **across runs** (stored
alongside snapshots/baselines — see
[`02-cli-reference.md`](02-cli-reference.md#data-storage-locations)). When
a process family is first seen above the CPU threshold, the timestamp is
recorded; on subsequent runs, if that family is still elevated, the elapsed
time is compared against the duration thresholds below. This is how it can
report "Antigravity has been using 95% CPU for over 40 minutes" rather than
only ever seeing an instantaneous snapshot.

**Fixed thresholds** (not currently configurable via `doctor.toml`):

| Constant | Value | Meaning |
|---|---|---|
| `SUSTAINED_CPU_PERCENT_THRESHOLD` | `50.0` | CPU% above which a process family starts being tracked for duration |
| `SUSTAINED_DURATION_WARN_MINUTES` | `15.0` | Minutes of sustained high CPU that triggers `WARN` |
| `SUSTAINED_DURATION_FAIL_MINUTES` | `40.0` | Minutes of sustained high CPU that triggers `FAIL` |
| `RAM_WARN_GB` | `4.0` | Per-family RAM usage that triggers `WARN` |
| `RAM_FAIL_GB` | `8.0` | Per-family RAM usage that triggers `FAIL` |

---

## Summary table

| Plugin | Skips when | Network access | Configurable thresholds | Cross-run state |
|---|---|---|---|---|
| `system` | never | no | none | no |
| `cpu` | never | no | yes | no |
| `memory` | never | no | yes | no |
| `battery` | no battery present | no | yes (macOS only, health data) | no |
| `disk` | never | no | yes | no |
| `git` | `git` not installed | **yes** (remote reachability) | none | no |
| `docker` | `docker` CLI not installed | no (local daemon only) | yes | no |
| `node` | `node` not on PATH | no | none | no |
| `python` | never (`python`/`python3` must exist) | no | none | no |
| `ai_ide` | never | no | none | **yes** |
