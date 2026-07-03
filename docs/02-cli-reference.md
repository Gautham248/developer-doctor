# CLI Reference

This is the complete, current surface of the `doctor` command. All examples
assume `doctor` is on your `PATH` (see [`01-installation.md`](01-installation.md));
substitute `uv run doctor` if you're running from source.

---

## `doctor` (default command)

Runs all applicable diagnostic plugins and prints a health report.

```bash
doctor
```

### Flags

| Flag | Description |
|---|---|
| `--json` | Output the full report as machine-readable JSON to stdout. |
| `--yaml` | Output the full report as YAML to stdout. |
| `--html` | Output a single, self-contained HTML report to stdout (no external CSS/JS). |
| `--ci` | Exit with status code `1` if any plugin reports `FAIL`. See [CI mode semantics](#ci-mode-semantics) below. |

`--json`, `--yaml`, and `--html` are **mutually exclusive** — passing more
than one produces an error and exits `1` before any diagnostics run.

`--ci` is **orthogonal** to the output format flags — `doctor --ci --json`
is a fully supported combination: you get machine-readable output on stdout
*and* a pipeline-friendly exit code. When combined with a machine-readable
format, human-readable text (discovery warnings, the "CI mode: critical
issues detected" banner) is suppressed from stdout, so scripts can safely
pipe the output to `jq`/`yq` without any stray text mixed in.

### Examples

```bash
doctor                              # human-readable report in the terminal
doctor --json | jq '.score'          # extract just the health score
doctor --yaml > report.yaml           # save a YAML snapshot
doctor --html > report.html && open report.html
doctor --ci; echo $?                    # 0 if healthy, 1 if any plugin FAILed
```

### CI mode semantics

- `--ci` treats **any single `FAIL`** status from any plugin as reason to
  exit non-zero. `WARN` statuses alone do **not** cause a non-zero exit —
  the working assumption is that CI pipelines should block on genuinely
  broken environments, not on things merely worth a human's attention.
- The full report is still printed/output normally before the exit code is
  decided — `--ci` never suppresses the report itself, only adds an exit
  decision after it.

Example GitHub Actions usage:

```yaml
- name: Verify developer environment
  run: doctor --ci
```

---

## `doctor snapshot`

Captures the current system state as a new historical snapshot, appended to
a growing history stored locally (see [Data storage](#data-storage-locations)
below).

```bash
doctor snapshot
```

Snapshots are capped at 90 stored entries — the oldest is dropped once the
cap is exceeded, so the history doesn't grow unbounded over months of daily
use. There is no flag to change this cap from the CLI today.

**Suggested usage**: run this on a schedule (cron/launchd) — a single manual
run doesn't give `doctor trend` (below) anything meaningful to analyze,
since trend analysis requires at least 3 data points per metric.

---

## `doctor diff [target]`

Compares the current system state against the historical snapshot closest
to a given point in time.

```bash
doctor diff                # defaults to "yesterday"
doctor diff today
doctor diff yesterday
doctor diff 7d              # 7 days ago
doctor diff 2026-06-25       # an ISO date
```

`target` accepts:
- `"today"` or `"yesterday"`
- `"Nd"` — N days ago, e.g. `"14d"`
- An ISO 8601 date or datetime string

If no snapshots exist yet, this errors with a clear message and exits `1`.
If snapshots exist but none are close to the requested time, it still picks
the *closest* one available — there's no "too far away" cutoff.

### Output

For each plugin, shows:
- Whether its `status` changed (e.g. `PASS → WARN`)
- Which numeric/metadata fields changed, with before/after values
- A summary line for the overall health score delta
- A dimmed list of unchanged plugins at the bottom

---

## `doctor trend`

Analyzes trends across **all** stored snapshots — this is deliberately
different from `doctor diff`, which only ever compares two points in time.

```bash
doctor trend
```

Requires **at least 3 snapshots** before it will report anything; if you
have fewer, it tells you exactly how many more you need and exits `1`.

### How trends are computed

- For every `(plugin, metric)` pair that appears as a flat numeric value in
  plugin metadata across at least 3 snapshots, the earliest and latest
  recorded values are compared.
- Changes smaller than **5%** (or, for metrics starting at zero, smaller
  than a negligible absolute delta) are filtered out as noise.
- **Known limitation, stated plainly**: this compares the earliest and
  latest data point, not a fitted regression line. It's simpler than true
  trend detection, but the ≥3-point requirement and the reported time span
  are what distinguish it from a plain two-point diff.
- **Known gap**: only flat numeric metadata fields are tracked. Nested
  structures (for example, the AI IDE plugin's per-process-family
  dictionary) are not flattened into trackable metrics yet.

### Example output

```
Trend Analysis
Computed across 6 snapshots

↑ disk.percent: 40.0 → 55.0 (+38% over 21d, 6 snapshots)
```

---

## `doctor baseline create`

Captures the current system state as **the** baseline — a single saved
snapshot representing a "known good" state, most useful right after fresh
machine setup or onboarding.

```bash
doctor baseline create
```

Running this again **overwrites** the previous baseline. There is only ever
one active baseline at a time (contrast with `doctor snapshot`, which
accumulates history).

## `doctor baseline compare`

Compares the current system state against the saved baseline.

```bash
doctor baseline compare
```

If no baseline has been created yet, this errors clearly and exits `1`.
Output format is identical in shape to `doctor diff` (they share the same
underlying diff renderer) — per-plugin status/metadata changes, overall
score delta, unchanged plugins listed separately.

---

## `doctor plugin create <name>`

Scaffolds a new, standalone, pip-installable third-party plugin package.

```bash
doctor plugin create postgres
doctor plugin create my-cool-thing
```

- `name` must start with a lowercase letter and contain only lowercase
  letters, digits, hyphens, or underscores.
- Creates a new directory `doctor-plugin-<name>/` in the current working
  directory. Errors if that directory already exists — never overwrites.
- See [`06-plugin-development.md`](06-plugin-development.md) for what gets
  generated and how to build on it.

## `doctor plugin validate <path>`

Loads a single plugin `.py` file and sanity-checks it — the same mechanism
used at runtime to load user plugins, so a pass here means the plugin will
actually load for real users too.

```bash
doctor plugin validate my_plugin.py
```

For every `DoctorPlugin` subclass found in the file, it reports: the
plugin's name/description/declared capabilities, the result of
`is_supported()`, and (if supported) the result of `run()` — including
catching and clearly reporting any exception the plugin raises, since
plugins must never raise from `run()`/`is_supported()` in production.

Exits `1` if the file fails to load, defines no plugins, or any plugin
raises an exception during validation.

## `doctor plugin lint <path>`

Runs `ruff` and `mypy` against a plugin file or directory.

```bash
doctor plugin lint doctor-plugin-postgres/
```

A tool that isn't installed is **skipped**, not treated as a failure —
a third-party plugin author may not have every dev tool available locally.
Exits `1` only if a tool that *did* run reported real issues.

## `doctor plugin package <path>`

Builds a plugin project into a wheel and sdist via `uv build`.

```bash
doctor plugin package doctor-plugin-postgres/
```

Requires a `pyproject.toml` in the target directory and `uv` on `PATH`.
Built artifacts land in `<path>/dist/`.

## `doctor plugin publish <path> [--repository REPO] [--yes]`

Validates and publishes a plugin package via `twine`.

```bash
doctor plugin publish doctor-plugin-postgres/
doctor plugin publish doctor-plugin-postgres/ --repository pypi --yes
```

**This is the one command in the entire CLI that performs a real,
irreversible external action** — uploading to a package index. It is built
with that in mind:

1. Always runs `twine check` first (fully local, no network access). If
   this fails, publishing stops immediately.
2. Defaults `--repository` to `testpypi`, not the real PyPI index — you
   must pass `--repository pypi` explicitly to publish for real.
3. Requires confirmation before uploading: either answer "yes" at the
   interactive prompt, or pass `--yes` to skip the prompt (the flag itself
   is still an explicit, deliberate opt-in — there is no way to publish
   silently by accident).

---

## Global behavior notes

### Plugin discovery warnings

If a user-local (`~/.config/doctor/plugins/`) or third-party (entry point)
plugin fails to load — a syntax error, a bad import, a name collision with
a built-in plugin — this is reported as a yellow warning line before the
report, in every command that runs diagnostics. These warnings are **never**
mixed into `--json`/`--yaml`/`--html` output, keeping machine-readable
output strictly parseable.

### Data storage locations

Snapshots, baselines, and AI IDE plugin state are stored as JSON under your
OS's standard application-data directory (via `platformdirs`), typically:

- macOS: `~/Library/Application Support/developer-doctor/`
- Linux: `~/.local/share/developer-doctor/`

Files of interest: `snapshots.json`, `baseline.json`. These are safe to
delete manually if you want a clean slate — a missing or corrupted state
file is never treated as an error, it's just treated as "no data yet."

### Exit codes summary

| Scenario | Exit code |
|---|---|
| Normal run, no `--ci` | `0` |
| `--ci` with no `FAIL` plugins | `0` |
| `--ci` with at least one `FAIL` plugin | `1` |
| `--json`/`--yaml`/`--html` used together (2+) | `1` |
| `doctor baseline compare` with no baseline saved | `1` |
| `doctor diff` / `doctor trend` with no/insufficient snapshots | `1` |
| `doctor plugin create` with invalid name or existing directory | `1` |
| `doctor plugin validate` on a file that fails to load or raises | `1` |
| `doctor plugin lint` with real lint failures | `1` |
| `doctor plugin package` on build failure | `1` |
| `doctor plugin publish` if `twine check` fails, or upload fails | `1` |
| `doctor plugin publish` aborted at the confirmation prompt | `0` (explicit abort, not an error) |
