---
version: 1
slug: "src-views-dashboardview-vue"
primary_target: "src/views/DashboardView.vue"
related_targets: ["src/App.vue","src/views/TopologyView.vue"]
---

Scope: GravityUI app shell and overview (/frontend-vue/), visitor mode Operate. Audience: homelab owner (daily glance, desktop and phone) and the self-hosting community (first opening). Job: know within seconds whether the network is fine, jump straight to what is not. Constraint: React UI stays the default; same features, shared texts and API.

## Direction contract
THESIS: The network as a transit map the operator draws themself: VLANs and links are coloured lines, devices are stations, multi-homed routers are interchanges; refuses the KPI-card-plus-table admin dashboard.
OWN-WORLD: Night network ground #0c0f14 with flat surfaces, white-ringed stations, thick rounded lines in a per-subnet palette the user can recolour, round line bullets, Hanken Grotesk with JetBrains Mono for addresses and numbers; light mode is the white daytime map with the same line colours.
STORY: The visitor reads the service status per line, sees the map with dropped stops struck in red, opens a station to act, and rearranges or reconnects the plan by dragging.
FIRST VIEWPORT: Left nav rail; top bar with search (Ctrl K), gateways, scan; status board with one row per network line; the network map fills two thirds, the service notices column on the right; groups follow below.
FORM: Liniennetzplan, grounded candidate 1 of re-roll 1 (user chose the pick); seed key 818d609b.
FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
