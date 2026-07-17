# ADR 0001 — Map stack and the float boundary

Date: 2026-07-17. Status: accepted.

## Decision 1: Leaflet 1.9.4, vendored, no build step

The incident room renders on Leaflet 1.9.4, committed into
`web/vendor/leaflet/` and verified against the SRI hashes published by
leafletjs.com for that release. Basemap tiles come from OpenStreetMap when
the browser is online, with attribution.

Rejected alternatives:

- MapLibre GL: requires a vector-tile pipeline and style tooling the current
  scenario does not need.
- Google Maps / Mapbox: API keys contradict the README promise that no key,
  cloud service, or model is required.
- CDN-loaded Leaflet: a network dependency for the core room; vendoring keeps
  the room usable offline.

Degradation rule: if tile requests fail, the room shows a one-line notice and
keeps rendering every kernel data layer over a plain background. The basemap
is an optional component; its absence degrades the picture, never the data.

## Decision 2: coordinates are display-only; the zone graph decides

`display.lon` / `display.lat` are floats and exist for the map alone. They
travel scenario file -> `room.geojson` and nowhere else. The sealed artifact
(`plan.json`) contains no floats; `lifeline/export.py` enforces this by
raising `CanonicalizationError` if a float reaches the canonical encoder, and
a test asserts the exported plan is float-free.

Planning authority remains the zone/route graph with integer ETA minutes,
as implemented in `lifeline/core.py`. If a geographic distance ever becomes a
planning input, it must enter as an integer (e.g. meters) computed at
ingestion and validated at the boundary — never as a float at plan time.
