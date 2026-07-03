# Installation

Developer Doctor is not yet published to PyPI or Homebrew (see
[`07-publishing.md`](07-publishing.md) for the plan to get there). Until then,
there are two ways to run it: as a contributor working from source, or as a
user who wants the `doctor` command available everywhere.

## Prerequisites

| Tool | Purpose | Install |
|---|---|---|
| Python 3.13+ | Runtime | via [`mise`](https://mise.jdx.dev) (recommended) or your system package manager |
| [`uv`](https://docs.astral.sh/uv/) | Dependency management, build backend, test runner | via `mise` or `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Git | Required for the Git plugin, and for cloning the repo | usually preinstalled on macOS/Linux |

Optional, only needed for the plugins that touch them:

- **Docker** — for the Docker plugin to report anything beyond "not installed."
- **Node.js** (any manager: `mise`, `nvm`, `volta`, `fnm`, or system) — for the Node plugin.

## Option A — Run from source (contributors, or anyone comfortable with `uv run`)

```bash
git clone https://github.com/Gautham248/developer-doctor.git
cd developer-doctor

mise use python@3.13
mise use uv

uv sync
uv run doctor
```

`uv sync` installs all runtime and dev dependencies into a project-local
`.venv/`. Every command in this documentation set assumes you're either
running via `uv run doctor ...` from inside the repo, or have installed the
tool per Option B below.

### Verifying the install

```bash
uv run doctor
uv run pytest -v
uv run ruff check .
uv run mypy doctor
```

If all four of those succeed, your environment is correctly set up.

## Option B — Install as a standalone command (recommended once you're past initial development)

This makes `doctor` available from any directory, not just inside the repo,
which matters a lot once you start using the Git identity checks, baselines,
and snapshots in your day-to-day projects.

```bash
cd developer-doctor
uv tool install --editable .
```

`--editable` means any change you make to the source under `doctor/` takes
effect immediately — no reinstall needed. This is the right mode while the
project is still under active development. Once the project has real
releases, you'd instead run:

```bash
uv tool install developer-doctor    # once published — see 07-publishing.md
```

After installing, confirm it's on your `PATH`:

```bash
which doctor
doctor --help
```

### A note on `mise` shims and `PATH`

If you use `mise` to manage `uv`/`python`, be aware that `mise`'s shims are
**directory-scoped** — a shim only resolves inside directories `mise` trusts
(your project checkouts). Running `uv` or a `uv tool install`-ed binary from
an untrusted directory (like `/tmp`) can fail with `command not found` even
though it's installed. If you hit this, either:

- run `mise trust` in the relevant directory, or
- resolve the absolute path once (`command -v uv`) and use that directly, or
- `uv tool install`-ed binaries generally land in `~/.local/bin`, which is
  usually on `PATH` unconditionally — prefer this for anything you want
  available everywhere without `mise` involved.

## Uninstalling

```bash
uv tool uninstall developer-doctor
```

## Next steps

- [`02-cli-reference.md`](02-cli-reference.md) — every command and flag.
- [`03-configuration.md`](03-configuration.md) — set up a `doctor.toml` for
  a real project.
