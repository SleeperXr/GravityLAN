# Roadmap

Where GravityLAN is heading, what is decided, and what is deliberately not on the list. Worked out in
October 2026 and updated with every work package that lands. Releases follow [RELEASING.md](RELEASING.md),
so no version numbers are promised here.

GravityLAN stays a **homelab tool**: one container, SQLite, a trusted home network. Ideas that would turn
it into an enterprise platform (SIEM export, signed audit trails, network access control) are out of scope.

## Status

| Phase | Goal | State |
|---|---|---|
| 0 · Release foundation | Calm, reproducible releases | ✅ done |
| 1 · One interface | GravityUI only | ✅ done; React removal follows (AP-14) |
| 2 · Safer administration | A logged-in session alone is no longer root on every host | 🟡 in progress |
| 3 · Events | Reliable notifications about new devices and changes | ⏳ after phase 2 |

**Release state:** `:latest` is 0.6.0. 0.7.0-rc.2 is on `:next` (rc.1 was never released). The next
candidate adds the backup import fix for older databases and the backup restore in the setup wizard.
0.7.0 carries security stages, so it stays on `:next` for 7 days before the final tag.

## Phase 0 · Release foundation ✅

- CI publishes images from tags: `vX.Y.Z` → `:X.Y.Z` + `:latest`, `vX.Y.Z-rc.N` → `:X.Y.Z-rc.N` + `:next`,
  `:dev` from `main` on request. A release re-tags the tested candidate instead of rebuilding it.
- [RELEASING.md](RELEASING.md): branches, test time by risk (7 days for migrations, background jobs,
  security stages and agent reporting; 2–3 days otherwise), checklist.
- Release gates in CI: the frozen database of the previous release upgrades cleanly; the agent version
  rises with every change in `agent/` and never for a server-only release.
- Backups include racks, ports and cabling.

## Phase 1 · One interface ✅

- GravityUI is the default interface ([ADR-003](adr/003-react-retirement.md)).
- GravityUI has its own copies of the API client, types and texts (no shared folder with React).
- The unused scan profiles are gone.

## Phase 2 · Safer administration 🟡

- ✅ **AP-11 Audit log** under Logs, next to the live log: who did what, from where, to which device,
  with which result. Kept 90 days; never secrets or terminal input; not part of backups.
- ✅ **AP-12 Password confirmation** before remote access, credential changes and instance actions.
  One area per confirmation, valid 10 minutes by default (adjustable 1–60).
- ⏳ **AP-13 No remote actions by token:** terminal, agent deployment and package updates only from a
  browser session with confirmation; master and API tokens are refused. Check `gravitylan_api` first.
- ⏳ **AP-14 Remove the classic React interface** and its build stage, in the release after GravityUI
  became the default.
- ⏳ **AP-10 Agent installer checksum:** shows the agent version and SHA-256, verifies the download and
  aborts on a mismatch. An integrity check, not a proof of origin.

## Phase 3 · Events ⏳

- Device history gets the event types "new device" and "IP changed", with a read state.
- An event only on a real change, none during the first inventory.
- Delivery through an outbox with up to three attempts; ntfy and Gotify presets next to webhooks.
- Acceptance: a new device seen by three scans sends exactly one notification.

## Decisions

**Accepted**
- `main` plus short-lived feature branches with a pull request and green CI; one pull request per work package.
- Password confirmation is adjustable (1–60 minutes); changing the duration needs a confirmation itself.
- The audit log complements the live log instead of replacing it.
- Which devices appear in the orbit is a per-device choice.
- Backups from older databases may hold duplicate rows; the import keeps the newest one instead of failing.

**Rejected**
- Checking scan targets against an allow-list: the size limits stay the only bound.
- Encrypting the SQLite database.

**Deferred**
- An agent protocol version, until the first incompatible agent API change.
- A vault key file (`VAULT_KEY_FILE`).
- Signed agent assets and image attestations.
- Phasing out stored SSH passwords, to be weighed once password confirmation has been in use.
- An event for "new open port".
- Integrations; Proxmox read-only is the first candidate.

## Open questions

- A migration that removes duplicate rows from old databases and adds the unique indexes they are missing.
