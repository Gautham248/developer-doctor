# Troubleshooting & FAQ

## Installation / environment issues

### `command not found: uv` (or `doctor`), even though I installed it

This is almost always a `mise` shim scoping issue. `mise`'s shims are
**directory-scoped** — they only resolve inside directories `mise` trusts
(your project checkouts). Running a `mise`-shimmed tool from `/tmp` or
another untrusted directory will fail even though it's genuinely installed.

Fixes, in order of preference:
1. `mise trust` in the relevant directory.
2. Resolve the absolute binary path once and use it directly:
   ```bash
   UV=$(command -v uv)   # run this from inside a trusted/project directory
   "$UV" run doctor ...
   ```
3. Prefer `uv tool install` (installs to `~/.local/bin`, generally on
   `PATH` unconditionally, no `mise` trust dance needed) over relying on
   `mise` shims for anything you want to run from arbitrary directories.

### `PATH` got polluted with `.` and now normal commands fail with "permission denied"

If you ever run `export PATH="$(dirname "$SOME_VAR"):$PATH"` where
`$SOME_VAR` was empty, `dirname ""` returns `.`, silently prepending your
**current directory** to `PATH`. If that directory happens to contain a
non-executable file/directory with the same name as a command you try to
run (e.g. a `doctor/` package directory shadowing the `doctor` command),
you'll see `zsh: permission denied: doctor` instead of a normal
"not found."

**Fix**: open a fresh terminal (safest way to guarantee a clean `PATH`)
rather than trying to manually unpick a polluted one. Always double-check
a variable is actually set before using it in a `PATH` export:
```bash
echo "$MY_VAR"   # confirm it's non-empty before using it in a PATH export
```

### `uv run doctor` fails with `ModuleNotFoundError: No module named 'doctor'`

Usually means the build backend is looking in the wrong place for the
package. Check `pyproject.toml`'s `[tool.uv.build-backend]` section:

```toml
[tool.uv.build-backend]
module-name = "doctor"
module-root = ""
```

`module-root = ""` is required if your package lives at the project root
rather than under a `src/` layout — `uv init`'s defaults assume `src/`,
which doesn't match this project's actual layout.

### `mypy` fails with `Library stubs not installed for "psutil"` (or similar)

Add the corresponding stub package as a dev dependency rather than an ad
hoc `pip install`:

```bash
uv add --dev types-psutil
```

(Substitute the relevant `types-*` package for whichever library mypy is
complaining about.)

---

## Plugin behavior questions

### Why does the `battery` plugin show "Managed by: system" / no health data on my Linux/Windows machine?

Cycle count and battery health are parsed from `system_profiler`, a
macOS-only tool. On other platforms, the plugin correctly falls back to
charge%/plugged-state only — this is documented, expected behavior, not a
bug. See [`04-plugins-reference.md`](04-plugins-reference.md#battery).

### The `python` plugin says my base interpreter is managed by `mise`, but I'm inside a `uv`-managed virtualenv — which is right?

Both, and they're reported as separate facts on purpose: "Active
virtualenv: .venv (created by uv)" and "Base interpreter managed by: mise"
are two different, both-true statements. The plugin deliberately
distinguishes "what created this venv" (read from the venv's `pyvenv.cfg`)
from "what manages the interpreter underneath it" (checked against
`sys.base_prefix`, not `sys.executable`) — see
[`04-plugins-reference.md`](04-plugins-reference.md#python) for why this
distinction matters.

### The `node`/`python` plugin misidentified my version manager

Both plugins use path-substring heuristics (checking if `/.nvm/`,
`/mise/`, `/.pyenv/`, etc. appear in a resolved binary path) — this is a
documented, known limitation, not a guaranteed-correct detection. Custom
or nonstandard install locations can cause a misdetection.

### Why is a Docker daemon that's not running reported as `WARN` instead of `FAIL`?

A stopped Docker Desktop is a common, low-severity, easily-fixed state
(you just haven't started it), not evidence of a broken environment. If
you want this to be treated more strictly (e.g. in a CI context where
Docker being down genuinely is a failure), there's currently no dedicated
config knob for this specific case — you'd need to either always ensure
Docker is running before invoking `doctor --ci`, or exclude `docker` from
`[thresholds]`/`[plugins]` scope for that context and check separately.

### `doctor trend` says "not enough snapshots" even though I've run `doctor snapshot` a few times

Trend analysis requires **at least 3 snapshots** before it reports
anything, and further requires that a given `(plugin, metric)` pair appear
in at least 3 of them. If you've disabled a plugin partway through your
snapshot history, or a plugin's `is_supported()` changed (e.g. you
plugged in a battery-less machine), that specific metric may not have
enough data points even if your total snapshot count is ≥3.

### `doctor trend` is showing tiny, noisy-looking changes as "trends"

Real short-interval data (snapshots taken minutes apart) genuinely does
fluctuate — CPU%, load averages, etc. are inherently noisy at a fine time
resolution. This isn't a bug; it's what happens when you feed the trend
computation real system noise instead of the smoother multi-week data it's
actually meant for. Trend analysis is far more meaningful when snapshots
are spread across days or weeks (see the suggested cron/launchd usage in
[`02-cli-reference.md`](02-cli-reference.md#doctor-snapshot)) rather than
run manually several times in a row.

---

## Configuration questions

### My `doctor.toml` doesn't seem to be picked up

1. Confirm you're running `doctor` from inside (or a subdirectory of) the
   directory containing `doctor.toml` — discovery searches **upward**
   from the current directory, never downward or sideways.
2. Confirm the TOML is actually valid — a malformed file is silently
   treated as "no config," with no error shown. Validate it manually:
   ```bash
   python -c "import tomllib; print(tomllib.load(open('doctor.toml', 'rb')))"
   ```
3. Set a deliberately extreme threshold as a sanity check (see
   [`03-configuration.md`](03-configuration.md#validating-your-config)).

### Can I have different `doctor.toml` files for different subdirectories of a monorepo?

Yes — since discovery searches upward from the current working directory,
running `doctor` from `packages/service-a/` will find
`packages/service-a/doctor.toml` before it finds one at the repo root, if
both exist.

---

## CI / automation questions

### `doctor --ci` exits 0 even though I see warnings in the output

This is intentional: `--ci` only treats `FAIL` as critical, not `WARN`. See
[`02-cli-reference.md`](02-cli-reference.md#ci-mode-semantics) for the full
reasoning. If you need warnings to also block a pipeline, you'd need to
parse `--ci --json` output yourself and check for any `WARN` status rather
than relying on the exit code alone.

### Can I run `doctor --ci --json` and get clean JSON with no extra text?

Yes — this is explicitly supported and tested. Discovery warnings and the
CI banner text are suppressed whenever a machine-readable format flag is
present, so `doctor --ci --json | jq .` works reliably.

---

## Data / privacy questions

### Where is snapshot/baseline data actually stored?

Under your OS's standard application-data directory via `platformdirs` —
see [`02-cli-reference.md`](02-cli-reference.md#data-storage-locations)
for exact paths. Nothing is ever sent anywhere external; there is no
telemetry in this project by design.

### How do I reset all stored history (snapshots, baseline, AI IDE tracking state)?

Delete the relevant JSON files from the state directory shown above. A
missing state file is always treated as "no data yet," never an error.

---

## Still stuck?

Check [`05-architecture.md`](05-architecture.md) if the question is about
*why* something is built a certain way rather than *how* to use it — a
lot of design decisions (what's enforced vs. self-attested, what's
deliberately out of scope) are documented there with their reasoning.
