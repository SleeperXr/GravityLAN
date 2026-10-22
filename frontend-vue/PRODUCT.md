# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users
Homelab operators who self-host GravityLAN (Docker, Unraid) on their own network. Two equal audiences: the owner, who glances at it daily to check that everything runs and digs in when something breaks, and the wider self-hosting community, for whom the first opening after installation should impress. Used about equally on a desktop or laptop (often a tab left open, sometimes a wall monitor) and on a phone for a quick status check.

## Product Purpose
GravityLAN turns a home network into a maintained inventory: it scans the subnets and VLANs, keeps every device with its services and interfaces, measures availability and latency (Health), monitors Linux hosts through a small agent (metrics, patches, updates), opens SSH sessions in the browser, and models racks and cabling. Success: the operator knows within seconds whether the network is fine, and finds and fixes what is not without switching tools.

## Positioning
"The network is alive": a living picture of the operator's own network, its devices, VLANs, gateways and status in real time, instead of a static list or a set of separate tools (uptime monitor, IPAM, inventory, terminal).

## Operating Context
Self-hosted in a trusted home network, one admin login. Two interfaces share one backend: the React UI under `/` (the default, stays unchanged) and GravityUI (Vue) under `/frontend-vue/` as the optional, opt-in interface. Both share texts (German and English) and the API client.

## Capabilities and Constraints
Overview with groups and a tile grid whose positions are shared with the React UI; device editor (general, services, interfaces/merge suggestions, history, agent); IP overview per /24 with areas and live discovery; Health with score, uptime bars, latency, incidents; agents with metrics, patches and update center; SSH terminal with stored keys; topology and racks; settings incl. scan subnets, router import, measurement data. GravityUI must keep the same feature set as the React UI. Light and dark mode, dark preferred as the default.

## Brand Commitments
Name GravityLAN. No violet or purple accents. Texts come from the shared translation files.

## Evidence on Hand
Demo backend (`scripts/dev_demo.py`) with synthetic devices, subnets, agents and health data. No real user testimonials or metrics; none may be invented.

## Product Principles
- Status first: what needs attention is visible before anything else.
- One place: every action on a device is reachable from where the device is shown.
- Live, not stale: data updates on its own and says how fresh it is.
- Same truth in both UIs: GravityUI never shows values the backend does not send.
