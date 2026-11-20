# Security matrix

Generated from the route declarations by `scripts/security_matrix.py`; do not edit by hand.
`tests/test_policy_matrix.py` fails when a route has no policy, when this file is out of date,
or when a route answers a caller differently than listed here.

Every route declares its access policy once, in its decorator: `dependencies=[policy(...)]`
(`backend/app/api/policy.py`). The policy checks, in this order:

1. **Setup**: until the first-run wizard is completed only routes marked *also during setup* answer
   (403 otherwise).
2. **Login**: a browser session (cookie), the master token or an API token (`Authorization: Bearer`;
   on a WebSocket also `?token=`). Missing or invalid: 401.
3. **Caller kind**: a caller kind marked `-` gets 403.
4. **Scope**: an API token needs the listed scope (403). `any` means every API token.
5. **Step-up**: the browser session must have confirmed the admin password for this class within
   `security.stepup_minutes` (403 with header `X-Step-Up: <class>`). `remote` is for browser
   sessions only; `credentials` and `instance` refuse API tokens, the master token passes.

Columns: **Session** = logged-in browser session, **Master** = master token (header, or the
deprecated cookie), **API token** = scope an API token needs. Public routes need no login; some
check a credential of their own, named under *Notes*.

## /api/agent

| Method | Path | Session | Master | API token | Step-up | Answers | Notes |
|---|---|---|---|---|---|---|---|
| POST | `/api/agent/adopt/{device_id}` | yes | - | - | remote | after setup |  |
| GET | `/api/agent/config/{device_id}` | yes | yes | `agent:read` | - | after setup |  |
| PATCH | `/api/agent/config/{device_id}` | yes | yes | `agent:write` | - | after setup |  |
| POST | `/api/agent/deploy/{device_id}` | yes | - | - | remote | after setup |  |
| GET | `/api/agent/download/agent` | public | public | public | - | always | The agent script itself; carries no secret. |
| GET | `/api/agent/download/config/{device_id}` | public | public | public | - | always | Own check: single-use install code, or the master token in the Authorization header (API tokens refused). |
| POST | `/api/agent/download/config/{device_id}` | yes | - | - | remote | after setup |  |
| GET | `/api/agent/download/install-sh/{device_id}` | public | public | public | - | always | Own check: install code (checked, not used up). |
| GET | `/api/agent/download/uninstall-sh/{device_id}` | public | public | public | - | always | The same script for every device id. |
| POST | `/api/agent/enroll/{device_id}` | yes | - | - | remote | after setup |  |
| GET | `/api/agent/global-metrics` | yes | yes | `agent:read` | - | after setup |  |
| GET | `/api/agent/metrics/{device_id}` | yes | yes | `agent:read` | - | after setup |  |
| GET | `/api/agent/overview` | yes | yes | `agent:read` | - | after setup |  |
| POST | `/api/agent/patches/{device_id}/prepare` | yes | - | - | remote | after setup |  |
| POST | `/api/agent/patches/{device_id}/query` | yes | - | - | remote | after setup |  |
| WebSocket | `/api/agent/patches/{device_id}/run-ws` | yes | - | - | - | after setup | Also: one-shot patch token from POST /api/agent/patches/{device_id}/prepare. |
| POST | `/api/agent/report` | public | public | public | - | always | Own check: agent token of the device (Authorization header). |
| GET | `/api/agent/status/{device_id}` | yes | yes | `agent:read` | - | after setup |  |
| POST | `/api/agent/uninstall/{device_id}` | yes | - | - | remote | after setup |  |
| WebSocket | `/api/agent/ws/{device_id}` | yes | yes | `agent:read` | - | after setup | Also the device's agent token as `?token=`. |

## /api/agents

| Method | Path | Session | Master | API token | Step-up | Answers | Notes |
|---|---|---|---|---|---|---|---|
| GET | `/api/agents` | yes | yes | `agent:read` | - | after setup |  |
| GET | `/api/agents/{device_id}` | yes | yes | `agent:read` | - | after setup |  |

## /api/audit

| Method | Path | Session | Master | API token | Step-up | Answers | Notes |
|---|---|---|---|---|---|---|---|
| GET | `/api/audit` | yes | yes | `settings:read` | - | after setup |  |

## /api/auth

| Method | Path | Session | Master | API token | Step-up | Answers | Notes |
|---|---|---|---|---|---|---|---|
| POST | `/api/auth/check` | yes | yes | any | - | after setup |  |
| GET | `/api/auth/cookie-security` | yes | yes | any | - | after setup |  |
| POST | `/api/auth/login` | public | public | public | - | always | Password login; at most 5 failed attempts per address and minute. |
| POST | `/api/auth/logout` | public | public | public | - | always | Ends the session of the cookie it is sent with. |
| POST | `/api/auth/master-token/rotate` | yes | - | - | credentials | after setup |  |
| GET | `/api/auth/me` | yes | yes | any | - | after setup |  |
| POST | `/api/auth/password` | yes | - | - | - | after setup | Current password confirmed in the request. |
| GET | `/api/auth/step-up` | yes | yes | any | - | after setup |  |
| POST | `/api/auth/step-up` | yes | - | - | - | after setup |  |
| GET | `/api/auth/tokens` | yes | yes | - | - | after setup |  |
| POST | `/api/auth/tokens` | yes | yes | - | credentials | after setup |  |
| DELETE | `/api/auth/tokens/{token_id}` | yes | yes | - | credentials | after setup |  |

## /api/backup

| Method | Path | Session | Master | API token | Step-up | Answers | Notes |
|---|---|---|---|---|---|---|---|
| GET | `/api/backup/export` | yes | yes | - | instance | after setup |  |
| POST | `/api/backup/import` | yes | yes | - | instance | after setup |  |

## /api/devices

| Method | Path | Session | Master | API token | Step-up | Answers | Notes |
|---|---|---|---|---|---|---|---|
| GET | `/api/devices` | yes | yes | `devices:read` | - | after setup |  |
| POST | `/api/devices/add-from-ip` | yes | yes | `devices:write` | - | after setup |  |
| POST | `/api/devices/bulk-delete` | yes | yes | `devices:write` | - | after setup |  |
| GET | `/api/devices/mac-conflicts` | yes | yes | `devices:read` | - | after setup |  |
| POST | `/api/devices/refresh-all` | yes | yes | `devices:write` | - | after setup |  |
| GET | `/api/devices/{device_id}` | yes | yes | `devices:read` | - | after setup |  |
| PATCH | `/api/devices/{device_id}` | yes | yes | `devices:write` | - | after setup |  |
| DELETE | `/api/devices/{device_id}` | yes | yes | `devices:write` | - | after setup |  |
| GET | `/api/devices/{device_id}/history` | yes | yes | `devices:read` | - | after setup |  |
| POST | `/api/devices/{device_id}/history/read-all` | yes | yes | `devices:write` | - | after setup |  |
| GET | `/api/devices/{device_id}/interfaces` | yes | yes | `devices:read` | - | after setup |  |
| POST | `/api/devices/{device_id}/interfaces` | yes | yes | `devices:write` | - | after setup |  |
| POST | `/api/devices/{device_id}/interfaces/merge` | yes | yes | `devices:write` | - | after setup |  |
| PATCH | `/api/devices/{device_id}/interfaces/{interface_id}` | yes | yes | `devices:write` | - | after setup |  |
| DELETE | `/api/devices/{device_id}/interfaces/{interface_id}` | yes | yes | `devices:write` | - | after setup |  |
| PUT | `/api/devices/{device_id}/mac` | yes | yes | `devices:write` | - | after setup |  |
| POST | `/api/devices/{device_id}/mac-observations/dismiss` | yes | yes | `devices:write` | - | after setup |  |
| POST | `/api/devices/{device_id}/refresh-info` | yes | yes | `devices:write` | - | after setup |  |
| POST | `/api/devices/{device_id}/refresh-services` | yes | yes | `devices:write` | - | after setup |  |
| POST | `/api/devices/{device_id}/services` | yes | yes | `devices:write` | - | after setup |  |

## /api/groups

| Method | Path | Session | Master | API token | Step-up | Answers | Notes |
|---|---|---|---|---|---|---|---|
| GET | `/api/groups` | yes | yes | `devices:read` | - | after setup |  |
| POST | `/api/groups` | yes | yes | `devices:write` | - | after setup |  |
| GET | `/api/groups/{group_id}` | yes | yes | `devices:read` | - | after setup |  |
| PATCH | `/api/groups/{group_id}` | yes | yes | `devices:write` | - | after setup |  |
| DELETE | `/api/groups/{group_id}` | yes | yes | `devices:write` | - | after setup |  |

## /api/health

| Method | Path | Session | Master | API token | Step-up | Answers | Notes |
|---|---|---|---|---|---|---|---|
| GET | `/api/health` | public | public | public | - | always | Docker and monitoring health check. |
| GET | `/api/health/device/{device_id}` | yes | yes | `devices:read` | - | after setup |  |
| GET | `/api/health/overview` | yes | yes | `devices:read` | - | after setup |  |
| GET | `/api/health/summary` | yes | yes | `devices:read` | - | after setup |  |

## /api/interfaces

| Method | Path | Session | Master | API token | Step-up | Answers | Notes |
|---|---|---|---|---|---|---|---|
| GET | `/api/interfaces/suggestions` | yes | yes | `devices:read` | - | after setup |  |
| POST | `/api/interfaces/suggestions/dismiss` | yes | yes | `devices:write` | - | after setup |  |

## /api/issues

| Method | Path | Session | Master | API token | Step-up | Answers | Notes |
|---|---|---|---|---|---|---|---|
| GET | `/api/issues` | yes | yes | `devices:read` | - | after setup |  |

## /api/logs

| Method | Path | Session | Master | API token | Step-up | Answers | Notes |
|---|---|---|---|---|---|---|---|
| GET | `/api/logs` | yes | yes | `settings:read` | - | after setup |  |
| WebSocket | `/api/logs/ws` | yes | yes | `settings:read` | - | after setup |  |

## /api/network

| Method | Path | Session | Master | API token | Step-up | Answers | Notes |
|---|---|---|---|---|---|---|---|
| GET | `/api/network/gateways` | yes | yes | `network:read` | - | after setup |  |
| POST | `/api/network/router-import/apply` | yes | yes | `network:write` | - | after setup |  |
| POST | `/api/network/router-import/preview` | yes | yes | - | credentials | after setup |  |
| GET | `/api/network/router-import/sources` | yes | yes | `network:read` | - | after setup |  |
| DELETE | `/api/network/router-import/sources/{provider}` | yes | yes | - | credentials | after setup |  |
| GET | `/api/network/subnets` | yes | yes | `network:read` | - | after setup |  |
| POST | `/api/network/subnets` | yes | yes | `network:write` | - | after setup |  |
| PATCH | `/api/network/subnets/{subnet_id}` | yes | yes | `network:write` | - | after setup |  |
| DELETE | `/api/network/subnets/{subnet_id}` | yes | yes | `network:write` | - | after setup |  |

## /api/notifications

| Method | Path | Session | Master | API token | Step-up | Answers | Notes |
|---|---|---|---|---|---|---|---|
| GET | `/api/notifications` | yes | yes | `devices:read` | - | after setup |  |
| POST | `/api/notifications/read-all` | yes | yes | `devices:write` | - | after setup |  |
| POST | `/api/notifications/{notification_id}/read` | yes | yes | `devices:write` | - | after setup |  |

## /api/scanner

| Method | Path | Session | Master | API token | Step-up | Answers | Notes |
|---|---|---|---|---|---|---|---|
| POST | `/api/scanner/discover` | yes | yes | `scanner:start` | - | after setup |  |
| GET | `/api/scanner/discovered` | yes | yes | `scanner:read` | - | also during setup, without login |  |
| PATCH | `/api/scanner/discovered/{host_id}` | yes | yes | `scanner:start` | - | after setup |  |
| DELETE | `/api/scanner/discovered/{host_id}` | yes | yes | `scanner:start` | - | after setup |  |
| POST | `/api/scanner/discovered/{host_id}/refresh-info` | yes | yes | `scanner:start` | - | after setup |  |
| GET | `/api/scanner/live-discovery` | - | yes | `scanner:start` | - | after setup | Authorization header only (a GET with side effects; browsers use the POST variant). |
| POST | `/api/scanner/live-discovery` | yes | yes | `scanner:start` | - | after setup |  |
| POST | `/api/scanner/quick-subnet-scan` | yes | yes | `scanner:start` | - | after setup |  |
| GET | `/api/scanner/scan-ip` | - | yes | `scanner:start` | - | after setup | Authorization header only (a GET with side effects; browsers use the POST variant). |
| POST | `/api/scanner/scan-ip` | yes | yes | `scanner:start` | - | after setup |  |
| POST | `/api/scanner/start` | yes | yes | `scanner:start` | - | also during setup, without login |  |
| POST | `/api/scanner/start-dashboard` | yes | yes | `scanner:start` | - | after setup |  |
| GET | `/api/scanner/status` | yes | yes | `scanner:read` | - | after setup |  |
| POST | `/api/scanner/stop` | yes | yes | `scanner:start` | - | also during setup, without login |  |
| GET | `/api/scanner/subnets` | yes | yes | `scanner:read` | - | also during setup, without login |  |
| GET | `/api/scanner/test` | yes | yes | `scanner:read` | - | after setup |  |
| WebSocket | `/api/scanner/ws` | yes | yes | - | - | also during setup, without login | API tokens are refused here (the query token must be the master token). |

## /api/services

| Method | Path | Session | Master | API token | Step-up | Answers | Notes |
|---|---|---|---|---|---|---|---|
| PATCH | `/api/services/{service_id}` | yes | yes | `devices:write` | - | after setup |  |
| DELETE | `/api/services/{service_id}` | yes | yes | `devices:write` | - | after setup |  |

## /api/settings

| Method | Path | Session | Master | API token | Step-up | Answers | Notes |
|---|---|---|---|---|---|---|---|
| GET | `/api/settings` | yes | yes | `settings:read` | - | after setup |  |
| POST | `/api/settings` | yes | yes | `settings:write` | - | after setup |  |
| GET | `/api/settings/proxmox` | yes | yes | `settings:read` | - | after setup |  |
| PUT | `/api/settings/proxmox` | yes | yes | - | credentials | after setup |  |
| DELETE | `/api/settings/proxmox` | yes | yes | - | credentials | after setup |  |
| POST | `/api/settings/proxmox/add-to-dashboard` | yes | yes | `settings:write` | - | after setup |  |
| GET | `/api/settings/proxmox/report` | yes | yes | `settings:read` | - | after setup |  |
| POST | `/api/settings/proxmox/sync` | yes | yes | `settings:write` | - | after setup |  |
| POST | `/api/settings/reset-db` | yes | yes | - | instance | after setup |  |
| GET | `/api/settings/telemetry` | yes | yes | `settings:read` | - | after setup |  |
| POST | `/api/settings/telemetry/purge` | yes | yes | `settings:write` | - | after setup |  |
| PUT | `/api/settings/telemetry/retention` | yes | yes | `settings:write` | - | after setup |  |

## /api/setup

| Method | Path | Session | Master | API token | Step-up | Answers | Notes |
|---|---|---|---|---|---|---|---|
| POST | `/api/setup/complete` | public | public | public | - | only during setup | First-run wizard only; 400 once setup is complete. |
| POST | `/api/setup/restore` | public | public | public | - | only during setup | First-run wizard only; 403 once setup is complete. |
| GET | `/api/setup/status` | public | public | public | - | always | Whether the first-run wizard is done. |

## /api/ssh

| Method | Path | Session | Master | API token | Step-up | Answers | Notes |
|---|---|---|---|---|---|---|---|
| GET | `/api/ssh/history` | yes | yes | - | - | after setup |  |
| DELETE | `/api/ssh/history/{entry_id}` | yes | yes | - | - | after setup |  |
| GET | `/api/ssh/keys` | yes | yes | - | - | after setup |  |
| POST | `/api/ssh/keys` | yes | yes | - | credentials | after setup |  |
| POST | `/api/ssh/keys/generate` | yes | yes | - | credentials | after setup |  |
| PATCH | `/api/ssh/keys/{key_id}` | yes | yes | - | credentials | after setup |  |
| DELETE | `/api/ssh/keys/{key_id}` | yes | yes | - | credentials | after setup |  |
| GET | `/api/ssh/known-hosts` | yes | yes | - | - | after setup |  |
| DELETE | `/api/ssh/known-hosts/{entry_id}` | yes | yes | - | credentials | after setup |  |
| GET | `/api/ssh/profiles` | yes | yes | - | - | after setup |  |
| POST | `/api/ssh/profiles` | yes | yes | - | credentials | after setup |  |
| PATCH | `/api/ssh/profiles/{profile_id}` | yes | yes | - | credentials | after setup |  |
| DELETE | `/api/ssh/profiles/{profile_id}` | yes | yes | - | credentials | after setup |  |
| POST | `/api/ssh/sessions/prepare` | yes | - | - | remote | after setup |  |
| GET | `/api/ssh/status` | yes | yes | - | - | after setup |  |
| WebSocket | `/api/ssh/terminal` | public | public | public | - | always | Own check: browser session cookie, or a one-shot ticket from POST /api/ssh/sessions/prepare issued to a session at the same address. |

## /api/summary

| Method | Path | Session | Master | API token | Step-up | Answers | Notes |
|---|---|---|---|---|---|---|---|
| GET | `/api/summary` | yes | yes | `devices:read` | - | after setup |  |

## /api/topology

| Method | Path | Session | Master | API token | Step-up | Answers | Notes |
|---|---|---|---|---|---|---|---|
| GET | `/api/topology/cabling` | yes | yes | `topology:read` | - | after setup |  |
| GET | `/api/topology/edges` | yes | yes | `topology:read` | - | after setup |  |
| GET | `/api/topology/links` | yes | yes | `topology:read` | - | after setup |  |
| POST | `/api/topology/links` | yes | yes | `topology:write` | - | after setup |  |
| PATCH | `/api/topology/links/{link_id}` | yes | yes | `topology:write` | - | after setup |  |
| DELETE | `/api/topology/links/{link_id}` | yes | yes | `topology:write` | - | after setup |  |
| GET | `/api/topology/map` | yes | yes | `topology:read` | - | after setup |  |
| GET | `/api/topology/nodes` | yes | yes | `topology:read` | - | after setup |  |
| PUT | `/api/topology/ports` | yes | yes | `topology:write` | - | after setup |  |
| POST | `/api/topology/rack-cables` | yes | yes | `topology:write` | - | after setup |  |
| PATCH | `/api/topology/rack-cables/{cable_id}` | yes | yes | `topology:write` | - | after setup |  |
| DELETE | `/api/topology/rack-cables/{cable_id}` | yes | yes | `topology:write` | - | after setup |  |
| POST | `/api/topology/rack-items` | yes | yes | `topology:write` | - | after setup |  |
| PATCH | `/api/topology/rack-items/{item_id}` | yes | yes | `topology:write` | - | after setup |  |
| DELETE | `/api/topology/rack-items/{item_id}` | yes | yes | `topology:write` | - | after setup |  |
| GET | `/api/topology/racks` | yes | yes | `topology:read` | - | after setup |  |
| POST | `/api/topology/racks` | yes | yes | `topology:write` | - | after setup |  |
| PATCH | `/api/topology/racks/{rack_id}` | yes | yes | `topology:write` | - | after setup |  |
| DELETE | `/api/topology/racks/{rack_id}` | yes | yes | `topology:write` | - | after setup |  |

## /api/webhooks

| Method | Path | Session | Master | API token | Step-up | Answers | Notes |
|---|---|---|---|---|---|---|---|
| GET | `/api/webhooks` | yes | yes | `settings:read` | - | after setup |  |
| POST | `/api/webhooks` | yes | yes | - | credentials | after setup |  |
| GET | `/api/webhooks/outbox` | yes | yes | `settings:read` | - | after setup |  |
| DELETE | `/api/webhooks/outbox/failed` | yes | yes | `settings:write` | - | after setup |  |
| POST | `/api/webhooks/outbox/{outbox_id}/retry` | yes | yes | - | credentials | after setup |  |
| GET | `/api/webhooks/test` | - | yes | `settings:write` | - | after setup | Authorization header only (a GET with side effects; browsers use the POST variant). |
| POST | `/api/webhooks/test` | yes | yes | `settings:write` | - | after setup |  |
| DELETE | `/api/webhooks/{webhook_id}` | yes | yes | - | credentials | after setup |  |

## GravityUI and health

| Method | Path | Session | Master | API token | Step-up | Answers | Notes |
|---|---|---|---|---|---|---|---|
| GET | `/` | public | public | public | - | always | Redirects to GravityUI. |
| GET | `/frontend-vue` | public | public | public | - | always | GravityUI files. |
| GET | `/frontend-vue/` | public | public | public | - | always | GravityUI files. |
| GET | `/frontend-vue/{full_path:path}` | public | public | public | - | always | GravityUI files. |
| GET | `/{full_path:path}` | public | public | public | - | always | Old addresses open GravityUI. |
