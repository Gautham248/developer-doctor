# Configuration — `doctor.toml`

Developer Doctor works with **zero configuration** out of the box — every
built-in plugin runs with sensible defaults. `doctor.toml` exists for when
you want to tune that behavior for a specific project or team.

## Where `doctor.toml` is discovered

`doctor` searches **upward** from your current directory for a file named
`doctor.toml`, the same way Git searches for a `.git` directory — so it
works no matter which subdirectory of a project you run `doctor` from.

If no `doctor.toml` is found anywhere up the directory tree, or if the file
exists but is malformed, `doctor` silently falls back to built-in defaults.
**A broken or missing config file is never fatal.**

## Full schema

```toml
[plugins]
enabled = []      # if non-empty, ONLY these plugins run (whitelist)
disabled = []     # ignored if `enabled` is set; otherwise a blacklist

[thresholds.cpu]
warn_percent = 70.0
fail_percent = 90.0
runaway_process_percent = 80.0

[thresholds.memory]
warn_percent = 80.0
fail_percent = 95.0
warn_swap_gb = 2.0
fail_swap_gb = 8.0

[thresholds.battery]
warn_health_percent = 80.0
fail_health_percent = 60.0
warn_cycle_count = 800
fail_cycle_count = 1000

[thresholds.disk]
warn_percent = 85.0
fail_percent = 95.0

[thresholds.docker]
warn_container_memory_gb = 8.0
fail_container_memory_gb = 16.0
```

Every field shown above is optional — specify only what you want to
override. Values you don't set fall back to the plugin's built-in default.

## `[plugins]` — enabling and disabling

### Blacklist mode (most common)

```toml
[plugins]
disabled = ["docker", "battery"]
```

Runs every plugin **except** the ones listed. Use this when a plugin isn't
relevant to a project (e.g. you don't use Docker on this repo) or is noisy
in an environment where its check doesn't make sense (e.g. `battery` on a
CI runner — though note `battery` already self-disables via
`is_supported()` on machines with no battery, so this is rarely necessary
for that specific case).

### Whitelist mode

```toml
[plugins]
enabled = ["system", "cpu", "memory"]
```

Runs **only** the plugins listed, regardless of what else is installed or
discovered. If `enabled` is non-empty, `disabled` is ignored entirely.

Plugin names match the `name` attribute of the plugin class — see
[`04-plugins-reference.md`](04-plugins-reference.md) for the full list of
built-in plugin names, or check a third-party plugin's source/README for
its name.

Note: even a plugin listed in `enabled` is still subject to its own
`is_supported()` check (e.g. `battery` on a desktop with no battery will
still be skipped).

## `[thresholds.<plugin>]` — tuning sensitivity

Only five built-in plugins expose tunable numeric thresholds today: `cpu`,
`memory`, `battery`, `disk`, and `docker`. The other five (`system`, `git`,
`node`, `python`, `ai_ide`) either report pure information with no
threshold to tune, or their checks are inherently binary (e.g. "is there an
active virtualenv?") rather than threshold-based.

Each threshold block accepts a partial override — you don't need to specify
every field, just the ones you want to change:

```toml
# Only override the CPU warning threshold; fail_percent and
# runaway_process_percent stay at their built-in defaults.
[thresholds.cpu]
warn_percent = 60.0
```

See [`04-plugins-reference.md`](04-plugins-reference.md) for exactly what
each threshold controls and its default value.

## Example: a stricter config for a resource-constrained CI runner

```toml
[plugins]
disabled = ["battery", "ai_ide"]

[thresholds.disk]
warn_percent = 70.0
fail_percent = 85.0

[thresholds.memory]
warn_percent = 70.0
fail_percent = 85.0
```

## Example: a lenient config for a beefy workstation

```toml
[thresholds.cpu]
warn_percent = 85.0
fail_percent = 97.0

[thresholds.memory]
warn_percent = 90.0
fail_percent = 98.0
```

## Team usage

Because `doctor.toml` is discovered by upward directory search, teams can
commit it to the root of a shared repository to enforce consistent
diagnostics across every contributor's machine — anyone running `doctor`
from anywhere inside that repo picks up the same thresholds and plugin
selection automatically, no per-developer setup required.

## Validating your config

There is currently no dedicated `doctor config validate` command. The
fastest way to confirm your `doctor.toml` is being read correctly is to set
a deliberately extreme threshold and confirm the corresponding plugin
reports the status you'd expect:

```toml
[thresholds.cpu]
warn_percent = 1
fail_percent = 2
```

```bash
doctor   # cpu should now show FAIL even under light load
```

Remove the deliberately extreme values once you've confirmed the config is
being picked up.
