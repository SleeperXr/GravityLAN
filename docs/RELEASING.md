# Releasing GravityLAN

How a change becomes an image on Docker Hub. The goal is calm releases: what ships was tested as it ships, and a pause
of a few weeks never leaves a half-finished release behind.

## Branches and tags

- `main` is always releasable. Work happens on short-lived feature branches and lands through a pull request with
  green CI.
- A release is a tag on `main`: `vX.Y.Z`. A release candidate is `vX.Y.Z-rc.N`.
- A patch branch `release/X.Y` exists only when a fix has to ship while `main` already carries unreleased work.
  It is cut from the `vX.Y.Z` tag, the fix lands on `main` first and is cherry-picked.

## Images

CI publishes images on tags ([`.github/workflows/release.yml`](../.github/workflows/release.yml)); nothing is pushed
from a laptop any more.

| Tag pushed | Images | Who gets it |
|---|---|---|
| `vX.Y.Z-rc.N` | `:X.Y.Z-rc.N`, `:next` | Testers who opt in. Never `:latest`. |
| `vX.Y.Z` | `:X.Y.Z`, `:latest` | Everyone. When the commit already went out as a release candidate, the RC image is re-tagged, not rebuilt: what ships is what was tested. |
| manual run of *Release images* on `main` | `:dev` | Test builds on request. |

The workflow runs the whole CI first and refuses a tag that does not match `VERSION`. It needs the repository secrets
`DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN`: a Docker Hub personal access token used for nothing else, with
**Read & Write** (no Delete) and an expiry date. A personal token cannot be limited to one repository (only
organisation tokens can), so it reaches every repository of the account; revoke it on its own if it leaks, and renew
it before it expires (`gh secret set DOCKERHUB_TOKEN`). Never paste it anywhere but that prompt.

## How long a release is tested

The time follows the risk of the changes, not how visible they are. A change that shows itself on the first start or
the first click needs days, not a week; what only shows over time (a migration, a new background job, the database
growing, agents over night, a security stage) gets the week.

| Release | Release candidate | Minimum time on `:next` |
|---|---|---|
| Changes that only show over time: a database migration, a new background job or scheduler change, a security stage, changes to how agents report | yes | 7 days |
| Changes that show right away: features, fixes, a changed default, refactoring covered by tests | yes | 2–3 days |
| Patch without a database migration | no, but the checklist below | — |

0.7.0 (GravityUI as the default, backups with rack cabling, the first image built by CI) is an example of the second
row: big for the user, but every part of it shows on the first start.

- A release candidate may stay out as long as needed; there is no deadline. A pause of several weeks simply means
  `:next` stays where it is.
- Any change during the RC phase means a new `rc.N`, and the minimum time starts again.
- The final tag goes on the commit of the last release candidate.

## Agent version

Every change in `agent/` raises `VERSION` in `agent/gravitylan-agent.py` (and the README agent badge) in the same pull
request; CI checks it ([`scripts/check_agent_version.py`](../scripts/check_agent_version.py)). A server release
without agent changes never raises it, since every agent version asks every installation to update its agents.

## Steps

1. **Prepare** on a branch, merged through a PR:
   - `VERSION`, then `python scripts/sync_version.py` (`frontend/package.json`, `backend/pyproject.toml`).
   - `frontend-vue/package.json` and the root version in both `package-lock.json` files (two lines each).
   - README release badge, `templates/gravitylan.xml` `<Changes>`.
   - Close `[Unreleased]` in `CHANGELOG.md` with the date of the release candidate.
   - Commit `chore(release): X.Y.Z`.
2. **Release candidate:** tag `vX.Y.Z-rc.1` on that commit and push the tag. Create a GitHub pre-release
   (`gh release create vX.Y.Z-rc.1 --prerelease`) with the notes. Run the checklist against `:next`.
3. **Wait** the minimum time. Fixes land on `main` through PRs; then tag `rc.2` on the new commit and start again.
4. **Release:** tag `vX.Y.Z` on the commit of the last release candidate and push it. CI re-tags the RC image as
   `:X.Y.Z` and `:latest`. Create the GitHub release (`gh release create vX.Y.Z --latest`) in the usual format.
5. **Freeze the database** of the release for the upgrade test, in a follow-up PR:
   `cd backend && python ../scripts/freeze_release_db.py` writes `backend/tests/fixtures/db/gravitylan-X.Y.Z.sql`.
   Frozen files are never edited.

A patch without a migration skips steps 2–3: tag `vX.Y.Z` directly after the checklist.

## Checklist

Tick it in the release candidate's GitHub pre-release (or the release, for a patch).

- [ ] **Fresh install:** empty data directory, setup wizard, first scan, GravityUI and the classic UI open.
- [ ] **Upgrade with real data:** a copy of a real data directory from the previous release starts, migrates and shows
      the same devices, racks, topology and agents.
- [ ] **Backup and restore on a fresh host:** export a backup, import it into a new instance, and check devices,
      racks, settings and saved SSH connections. (Saved SSH keys only work there with the same vault key, see
      [SECURITY.md](../SECURITY.md).)
- [ ] **What changed:** every CHANGELOG entry of the release tried once.
- [ ] **Agents:** an agent of the previous version keeps reporting; if the agent version changed, the update from the
      UI works.
- [ ] **Tag and commit:** the final tag points at the commit of the last release candidate.

Automated in CI on every push ([`backend/tests/test_release_upgrade.py`](../backend/tests/test_release_upgrade.py)):
every frozen release database upgrades to the current schema without errors and without losing rows, and a backup
exported from it and imported on a fresh instance exports the same again.
