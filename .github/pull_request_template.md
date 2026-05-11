## Summary

<!-- 1-3 sentences. What changed, why. -->

## Test plan

<!-- Bulleted checklist of how this was verified. -->

- [ ]

## Deploy considerations

<!-- The default for every box below is NO. Tick a box only if it applies to
     this PR. If you tick a box, you MUST address the follow-up before merge. -->

- [ ] **New required environment variables.** If checked: list them, name the
      service(s) that need them (Vercel / Railway), and confirm they're set
      in the production environment **before** this PR merges. Update
      [`docs/env-vars.md`](../docs/env-vars.md).
- [ ] **New required third-party service.** (e.g., new Clerk app, new AWS
      resource, new external API). If checked: confirm the service is
      provisioned in production and any BAAs are in place before merge.
- [ ] **Migration required before deploy.** If checked: describe the migration
      and the rollout order.
- [ ] **Breaking API change** for SDK consumers. If checked: bump CHANGELOG
      under `[Unreleased]` and add a `MIGRATION.md` entry.
- [ ] **New build-time or runtime dependency** that changes the build
      command, container image, or system packages.

## Linked issues

<!-- Closes #N, Refs #N. Or n/a. -->

---

*By merging, the author confirms they've configured any new env vars in the
appropriate deploy environment(s). The build-time `check-env` guard and
post-deploy smoke test will catch obvious misses, but the author is the
first line of defense.*
