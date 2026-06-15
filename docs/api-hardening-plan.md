# GravityLAN API Hardening & KI-Readiness

## Kontext
- Server: 192.168.100.254:8000
- API Version: 0.3.0 (FastAPI)
- Aktueller Stand: 72 Endpunkte, OpenAPI Spec verfügbar unter /openapi.json
- Auth-Modell existiert (Bearer + Query-Token), aber kein Scoping

## 4 kritische Aufgaben (in dieser Reihenfolge)

### A) KRITISCH: Secrets-Leak in /api/settings fixen [ERLEDIGT]
Das GET `/api/settings` liefert aktuell `api.master_token` und `api.admin_password` (argon2id-Hash, aber trotzdem) im Klartext. Selbst Read-Only-Token reichten aus, um an diese Secrets zu kommen.

**TODO:**
1. In der Response-Serialisierung von `/api/settings` diese zwei Keys rausfiltern. (Erledigt: Keys werden für alle Anfragen ausgefiltert)
2. Bestehende Tokens nach dem Fix invalidieren, weil sie den Master-Token leaken (Benutzeraktion in WebUI erforderlich).
3. Audit-Log hinzufügen: wann wurde `/api/settings` aufgerufen.
4. Tests: Read-Only-Token darf NIE `master_token`/`admin_password` sehen. (Erledigt: `test_settings_no_secrets_leak` hinzugefügt)

### B) Token-Scoping implementieren
- Scopes: `["devices:read", "devices:write", "scanner:start", "settings:read", ...]`
- Token-Erstellung: `POST /api/auth/tokens` erweitern um `scopes: []`
- Jeder Endpoint deklariert in OpenAPI, welche Scopes er braucht
- Standard für neue Tokens: nur read-Scopes, kein Schreibzugriff
- Backward-Compat: bestehende Token-Typen behalten

### C) KI-spezifische Endpoints hinzufügen
- `POST /api/agent/chat` — Natural Language → Tool-Use Pattern
  Body: `{message: str, context?: dict}`
  Response: `{action: "scan_subnet|restart_device|...", params: {...}, explanation: str}`
- `GET /api/summary` — Aggregierter 1-Shot-Healthcheck
  Response: `{devices: {total, online, offline}, agents: {...}, scanner: {...}, issues: [{type, device_id, message}]}`
- `POST /api/webhooks` — Event-Subscription
  Body: `{url, events: ["device.offline", "scan.complete"]}`
- `GET /api/agent/metrics/summary/{device_id}?range=24h` — aggregierte Metriken
  Response: `{cpu: {avg, max, p95}, ram: {...}, temp: {...}, uptime_pct, anomalies: []}`

### D) Observability & Schutz
- Rate-Limiting Middleware (slowapi oder eigene), Default: 60 req/min, konfigurierbar pro Token
- Response-Header: `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`
- Request-Logging mit Token-ID (nicht Token-Wert!)
- OpenAPI Security-Schemes korrekt deklarieren (bisher leer)

## Akzeptanzkriterien
- [x] `/api/settings` zeigt KEINE `master_token` oder `admin_password` mehr
- [ ] Neuer Token hat konfigurierbare Scopes
- [ ] OpenAPI Spec listet korrekte Security-Schemes
- [ ] `/api/summary` antwortet in <200ms mit allen relevanten Daten
- [ ] `/api/agent/chat` verarbeitet mindestens 5 Intent-Typen (`scan`, `status`, `diagnose`, `restart`, `find_device`)
- [ ] Rate-Limit greift und ist in Headers sichtbar
- [ ] Tests für alle 4 Punkte, CI-pflichtig
