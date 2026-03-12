# AutoMagic Repo Instructions

## Release Versioning

When the user asks to `commit and push` a change intended for HACS users:

1. Bump the integration version in `custom_components/automagic/manifest.json`.
2. Use the next patch version by default.
3. Keep the GitHub release tag in sync with the manifest version, for example:
   - manifest `0.2.1`
   - GitHub release/tag `v0.2.1`
4. Do not reuse the previous HACS version number once a newer user-visible update is being shipped.
5. Treat the GitHub release as required for HACS to see the new downloadable version.

## Validation

Before committing and pushing:

1. Update or add tests for version-sensitive changes.
2. Run:
   - `python3 -m pytest`
   - `python3 -m compileall custom_components tests`
   - `node --check custom_components/automagic/www/automagic-card.js`

## Ordering

If the user explicitly asks to `commit and push`, keep the commit, push, and GitHub release publication as the final steps after validation passes.
