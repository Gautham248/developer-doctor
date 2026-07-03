# Publishing Developer Doctor

This covers releasing **the core `developer-doctor` project itself** — not
publishing a third-party plugin (see
[`06-plugin-development.md`](06-plugin-development.md#validating-linting-packaging-publishing)
for that).

**Current status: not yet published anywhere.** This doc documents what's
already built and verified, and exactly what remains as deliberate,
irreversible manual steps that should never happen accidentally.

## What's already done

- `pyproject.toml` has complete metadata: description, MIT license
  (SPDX form), classifiers, keywords, and project URLs.
- A root `LICENSE` file (MIT) exists.
- `.github/workflows/release.yml` — a complete, validated (via
  `actionlint`, zero errors) GitHub Actions workflow that builds, tests,
  and publishes on tag push.
- `homebrew/developer-doctor.rb` — a formula template, style-checked via
  `brew style` (clean except for the intentionally-placeholder `sha256`).

## What's deliberately not done yet

Cutting an actual release is a genuine, irreversible decision — not
something to bundle into routine development work. Specifically:

- No `v*.*.*` git tag has been pushed.
- No PyPI Trusted Publisher relationship has been configured.
- No `homebrew-doctor` tap repository has been created.
- No real `sha256` exists for the Homebrew formula (it can only be
  computed from a tarball that exists after a real release).

---

## Release workflow overview

`.github/workflows/release.yml` triggers **only** on a pushed tag matching
`v*.*.*` (e.g. `v0.1.0`) — an ordinary `git push` to `main` never triggers
it.

```
tag push (v*.*.*)
    → run full test suite (uv run pytest) — release blocked if this fails
    → uv build (wheel + sdist)
    → twine check dist/*  — same safety check the plugin SDK's publish uses
    → upload build artifact
    → [job: publish-pypi]  → PyPI Trusted Publishing (OIDC, no stored token)
    → [job: github-release] → attach artifacts to a new GitHub Release,
                                 auto-generated release notes
```

### Why Trusted Publishing instead of a stored API token

The `publish-pypi` job uses PyPI's
[Trusted Publishing](https://docs.pypi.org/trusted-publishers/) via OIDC
rather than a `PYPI_API_TOKEN` repository secret. This means:

- No long-lived credential is stored in the repository at all.
- PyPI will **refuse** the upload until you explicitly configure the
  trusted publisher relationship on PyPI's side, pointing at this exact
  repository, workflow file, and environment name (`pypi`). This is itself
  a deliberate, manual, one-time setup step — the workflow existing in the
  repo cannot silently publish anything until that relationship exists.

### The `environment: pypi` gate

The `publish-pypi` job runs against a GitHub Environment named `pypi`. You
can (and should, before a first real release) configure that environment
in the repo's Settings → Environments with a required reviewer / manual
approval gate — an extra checkpoint even after a tag is pushed.

---

## Step-by-step: cutting a real release (when you're ready)

**Do this deliberately, not as part of routine work.** Version numbers on
PyPI are permanent — once `0.1.0` is uploaded, that exact version string
can never be reused, even if the release is later yanked.

1. **Configure the PyPI Trusted Publisher** (one-time, before the first
   release):
   - Create the project on PyPI if it doesn't exist yet (or configure
     this from a fresh account — trusted publishing can be set up before
     any version has ever been uploaded).
   - Under the project's PyPI settings → Publishing, add a new pending
     publisher: GitHub repository `Gautham248/developer-doctor`, workflow
     `release.yml`, environment `pypi`.

2. **Bump the version** in `pyproject.toml` if `0.1.0` isn't what you want
   to ship first.

3. **Tag and push**:
   ```bash
   git tag v0.1.0
   git push --tags
   ```

4. **Watch the Actions run.** If tests fail, the release stops before
   anything is built or published — nothing partial gets uploaded.

5. **Verify**: `pip install developer-doctor` (or
   `uv tool install developer-doctor`) from a clean environment, and check
   the GitHub Releases page for the attached artifacts.

6. Only **after** a real release exists, move on to the Homebrew steps
   below — the formula needs a real tarball to hash.

---

## Homebrew formula: remaining steps

See `homebrew/README.md` in the repo root for the full checklist. Summary:

1. Cut a real release (above) first — the formula's `url` points at a
   tagged source tarball that doesn't exist until then.
2. Compute the real hash:
   ```bash
   curl -sL https://github.com/Gautham248/developer-doctor/archive/refs/tags/v0.1.0.tar.gz | shasum -a 256
   ```
3. Replace `REPLACE_ME_AFTER_FIRST_RELEASE` in
   `homebrew/developer-doctor.rb` with that hash.
4. Generate `resource` blocks for each Python dependency (`gitpython`,
   `platformdirs`, `psutil`, `pydantic`, `pyyaml`, `rich`, `typer`).
   **Do not hand-write these** — Homebrew's own tooling resolves the
   correct pinned versions and hashes; a hand-written block is very likely
   to be subtly wrong.
5. Create a new GitHub repository named `homebrew-doctor` under the same
   account, and copy the formula into it (root or a `Formula/` subdirectory,
   per current Homebrew tap conventions).
6. Test locally before publishing:
   ```bash
   brew install --build-from-source ./developer-doctor.rb
   ```
7. Once verified, users can install via:
   ```bash
   brew tap gautham248/doctor
   brew install developer-doctor
   ```

---

## Channels explicitly out of scope for now

Per the project's own prioritization (first-class vs. future/roadmap
channels), these are **not** being built in the current phase:

- Standalone binaries (PyInstaller/Nuitka)
- Winget, Scoop, apt, snap

These remain real future work, just not blocking the PyPI/Homebrew path.

---

## Pre-release checklist

Before pushing a release tag for the first time, confirm:

- [ ] `uv run pytest -v` — full suite passes
- [ ] `uv run ruff check .` and `uv run mypy doctor` — both clean
- [ ] `uv build` succeeds locally and `dist/` isn't accidentally committed
      (`dist/` is in `.gitignore`)
- [ ] Version number in `pyproject.toml` is what you actually intend to
      ship
- [ ] PyPI Trusted Publisher relationship is configured
- [ ] You've genuinely decided this version number should be permanent
