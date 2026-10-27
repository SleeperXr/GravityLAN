# ADR-003: Retire the React Frontend in Favour of GravityUI (Vue)

**Status:** Accepted
**Date:** 2026-10-27
**Deciders:** Project owner

## Context

Since 0.5.0 GravityLAN ships two complete web UIs from the same backend: the original React app (`frontend/`, served at
`/`) and GravityUI in Vue 3 (`frontend-vue/`, served at `/frontend-vue`), with a switch in both and a default-UI setting.
Every feature, fix and screenshot has to be built twice, and the two UIs drift apart. GravityUI is the direction the
project wants to go.

## Decision

1. **GravityUI becomes the only UI.** Once it covers everything the React app does, it becomes the default for new and
   existing installs.
2. **One version as fallback.** The release that makes GravityUI the default still ships the React app behind the
   switch. The release after that removes `frontend/` and its build stage.
3. **No new investment in React until then.** New features, refactors, tests and polish go into `frontend-vue/` only.
   React gets bug fixes only where a user would otherwise be stuck.

## Consequences

- Before switching the default, the feature-parity gaps have to be listed and closed (tracked in
  `docs/PLAN-vue-migration.md`).
- GravityUI still imports the API client and shared types from the React tree (`@shared` → `frontend/src`, see
  `frontend-vue/src/api/client.ts`). They have to move into `frontend-vue/` (or a shared package) before `frontend/` can
  be deleted.
- Code-health findings in React components (for example `HealthDetailDrawer`, `HealthView`, `RouterImportPanel`) are
  accepted and not refactored.
- The Docker image gets smaller and the build faster once the React stage is removed.
