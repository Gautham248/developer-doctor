# Homebrew Tap Setup (not yet executed)

This formula is a template. To actually publish it:

1. Cut a real release: `git tag v0.1.0 && git push --tags` (triggers
   `.github/workflows/release.yml`).
2. Compute the real sha256 of the release tarball:
curl -sL https://github.com/Gautham248/developer-doctor/archive/refs/tags/v0.1.0.tar.gz | shasum -a 256

3. Replace `REPLACE_ME_AFTER_FIRST_RELEASE` in `developer-doctor.rb` with that hash.
4. Generate the `resource` blocks for each Python dependency (gitpython,
   platformdirs, psutil, pydantic, pyyaml, rich, typer) — Homebrew's own
   `brew` tooling or `poet` can do this; do not hand-write these hashes.
5. Create a new GitHub repo named `homebrew-doctor` under your account.
6. Copy `developer-doctor.rb` into that repo's root (or a `Formula/` subdir).
7. Test locally before publishing: `brew install --build-from-source ./developer-doctor.rb`
8. Once it works: `brew tap gautham248/doctor` (users) resolves to
   `github.com/Gautham248/homebrew-doctor`.
