# LIFELINE — Day 1 build plan (2026-07-17)

Status: proposal for the first construction day. Grounded in the live tree as of
commit `807adfc` (verified 2026-07-16): `lifeline/core.py` (132-line
deterministic planner, 3 tests passing on Python 3.12.3), `web/index.html`
(static landing with a decorative CSS map, hardcoded data), and the
architecture in `docs/LIFELINE_OS_EN.md`.

Goal of the day: complete step 2 of the construction sequence in
LIFELINE_OS_EN.md — a working **Incident Room** over one synthetic flood
scenario, with a real map, fed exclusively by the deterministic kernel, plus
the geographic data contract that makes it possible.

---

## 0. Decisions made up front (with rationale)

### D1 — Map stack: Leaflet 1.9.x, vendored, no build step
- **Chosen:** Leaflet, vendored into `web/vendor/` (js + css + marker assets).
  OpenStreetMap raster tiles when online, with attribution.
- **Rejected:** MapLibre GL — needs a vector-tile pipeline and styling work the
  day-1 scenario does not require. Google/Mapbox — API keys violate the "no
  API key, cloud service, or model required" promise in the README.
- **Degradation rule:** if tile fetches fail (offline), the basemap disappears
  but every GeoJSON layer still renders over a plain background. An absent
  optional component degrades the feature, never the core.
- **No bundler:** the site stays static (`python3 -m http.server`). Revisit
  only if the room outgrows plain JS.

### D2 — Coordinates are cosmetic; the zone graph decides
`lat`/`lon` are floats and therefore **never enter the decision path or any
sealed payload**. Planning authority remains the zone/route graph with integer
ETAs, exactly as `core.py` works today. Coordinates exist only in
`room.geojson` (display layer). If a geographic distance ever becomes a
planning input, it enters as integer meters computed at ingestion, never as a
float at plan time. This boundary gets an ADR (`docs/adr/0001-map-stack.md`).

### D3 — Kernel is the single source of truth for the room
`web/index.html` currently hardcodes illustrative data. The new room page
renders **only** files exported by the kernel (`room.geojson`, `plan.json`).
The landing page stays as-is (marketing/illustrative, already labeled).

### D4 — Sibling-repo reuse (surveyed 2026-07-16)
| Repo | Verdict | Day-1 use |
|---|---|---|
| `~/cronos` | stdlib-only, importable (`CronosTracer`, Fraction confidence, hash chain) | Stretch block 4: trace every planning run |
| `~/mneme` | stdlib-only, importable (`custody.py`, `trust.py`, quarantine) | Day 2+: per-report custody |
| `~/corvus` | importable analyzers, Fraction-safe | Day 2+: freshness/duplicate/contradiction validators |
| `~/MUTANTE_v2` | `engine/bayesian.py` Thompson Sampling extractable | Phase 5 (adversarial lab), per safe-adoption path |
| `~/stigmergy` | pattern only (CockroachDB-coupled) | Copy canonical-JSON + Fraction discipline idioms |
| `~/audit-chain` | reference spec (C/Rust/Java) | Use CRONOS/MNEME Python chains instead |

Day 1 imports **nothing** except (stretch) CRONOS. Resist wiring everything at
once; the construction sequence in LIFELINE_OS_EN.md is deliberate.

---

## Block 0 — Session protocol (15 min)

```bash
cd ~/lifeline
git tag -a "pre-session-$(date +%Y%m%d-%H%M%S)" -m "restore point before AI session"
git checkout -b feat/incident-room-map
python3 -m pytest -q        # expect: 3 passed (baseline)
```

Forward-only git for the whole session: commit/merge/revert only.

## Block 1 — Geographic data contract, kernel side (60–90 min)

New module `lifeline/scenario.py` + scenario file `scenarios/flood_v1.json`.

1. **Schema v1** (`"schema_version": 1` mandatory, reject unknown versions):
   - `zones`: `zone_id`, `name`, `kind` (bank/base/shelter-site), `display`
     object with `lon`/`lat` (floats, display-only by contract).
   - `requests`/`resources`/`shelters`/`routes`: the existing `core.py` fields
     **plus** the minimum provenance contract from LIFELINE_OS_EN.md:
     `source`, `source_type`, `observed_at`, `verification_state`
     (`verified` / `unverified` / `conflicting`), `freshness`
     (`high` / `medium` / `low`).
2. **Boundary validation** (fail closed, clear errors at load, never deep in
   the planner): unknown zone reference, negative capacity/people, lon/lat out
   of range, unknown enum value, duplicate IDs.
3. **Verification gate** (honest degradation): only `verified` requests enter
   `plan_response`. `unverified`/`conflicting` requests bypass planning and
   come out as `NEEDS_HUMAN_REVIEW` with reason `"unverified report"` /
   `"conflicting reports"` — uncertainty is shown, never hidden.
4. `core.py` is **not rewritten**; `scenario.py` adapts loaded data into the
   existing dataclasses. Any change to `core.py` is a surgical patch.
5. Tests: loader happy path, each rejection case, verification gate.

## Block 2 — Canonical export and seal (60 min)

New module `lifeline/export.py`.

1. Canonical encoder: type-tagged, recursively key-sorted, `bool` checked
   before `int`, `CANONICALIZE_VERSION = 1`. Copy the idiom from
   `~/stigmergy` / `~/mneme` `canonical.py`; do not invent a divergent one.
2. Outputs to `out/`:
   - `plan.json` — proposals, statuses, reasons, per-proposal audit hashes.
     **No floats anywhere in this file.**
   - `plan.seal.json` — SHA-256 over the canonical `plan.json` bytes +
     canonicalize version + SHA-256 of the input scenario bytes. Timestamp
     recorded here, outside the sealed payload.
   - `room.geojson` — display layer: zone/request/resource/shelter Points,
     route LineStrings with `state` (open/closed) and provenance properties.
     Floats allowed here only.
3. CLI: `python3 -m lifeline plan scenarios/flood_v1.json --out out/`.
4. **Determinism proof (test, not claim):** load the scenario with shuffled
   input order, run the export in a fresh subprocess twice, assert identical
   seal digests. Also assert `plan.json` contains no JSON numbers with a
   fractional part.

## Block 3 — The map in the incident room (90 min)

1. Vendor Leaflet: download 1.9.x dist into `web/vendor/leaflet/`; commit it
   (offline-first, no CDN — the strict-CSP/no-external-deps posture).
2. New page `web/room.html` (landing untouched):
   - `fetch('../out/room.geojson')` + `fetch('../out/plan.json')`; if either
     is missing, show "no exported plan found — run the kernel" instead of
     fake data.
   - Layers with toggles: requests (coral), resources (blue), shelters
     (green), routes styled by state; closed routes dashed coral and clearly
     labeled, producing no proposals.
   - Every popup shows provenance: source, observed_at, verification_state,
     freshness. Evidence is not narrative.
   - Side panel from `plan.json`: PROPOSED entries with resource → pickup →
     shelter, ETA, reasons; NEEDS_HUMAN_REVIEW entries with their reasons,
     visually loud, never dropped.
   - Approve/Reject buttons change **local UI state only** and append to a
     visible "pending human action" log. No dispatch, no backend, no
     persistence yet — approvals become real in the roadmap's step 3.
3. Tile layer: OSM with attribution; on tile error, keep data layers on plain
   background (test by loading with network disabled).
4. Serve: `cd web && python3 -m http.server 8788 --bind 127.0.0.1` (as README).

## Block 4 — Stretch: CRONOS trace per planning run (60 min, may slip to day 2)

```bash
pip install -e ~/cronos   # stdlib-only, verified importable
```
Wrap the CLI run in `CronosTracer(store, agent_id="lifeline-kernel", ...)`:
scenario digest as evidence, one step per exclusion reason, final `decide()`
with Fraction confidence. Trace SQLite under `out/trace.sqlite`. If the
integration fights back, stop and ship blocks 1–3; this is optional by design
("if the model is unavailable, the plan and its audit trail still exist" —
the same holds for any optional dependency).

## Block 5 — Docs, checklist, commit (30 min)

1. `docs/adr/0001-map-stack.md`: D1 + D2 (Leaflet choice, float boundary).
2. README: room run instructions (`kernel export → serve → open room.html`).
3. Pre-commit checklist from the engineering guide: tests run and output read,
   no float in sealed path, determinism test green, `git status` verified.
4. Commit(s) in English, why-focused, e.g.
   `feat: add geographic scenario contract and sealed plan export`,
   `feat: render kernel-exported incident room on a real map`.

---

## Definition of done for the day

- [ ] `scenarios/flood_v1.json` loads, validates, and rejects each bad-input case.
- [ ] Unverified/conflicting requests visibly reach NEEDS_HUMAN_REVIEW, never a proposal.
- [ ] `plan.json` + `plan.seal.json` + `room.geojson` export deterministically
      (shuffled-input, fresh-process test green).
- [ ] No float in `plan.json` or anything sealed; floats confined to `room.geojson`.
- [ ] `room.html` renders the exported scenario on Leaflet, degrades without
      tiles, and shows provenance in every popup.
- [ ] All tests pass; new tests cover loader, gate, determinism.
- [ ] ADR written; README updated; forward-only commits on `feat/incident-room-map`.

## Explicitly out of scope for day 1 (backlog, in order)

1. MNEME per-report custody chains and actor quarantine.
2. CORVUS validators (freshness, duplicate, contradiction) feeding
   `verification_state`.
3. Alternative-plan simulation with visible assumptions (Plans A–D).
4. MUTANTE adversarial laboratory + Thompson Sampling verification budget
   (offline laboratory first, per the safe adoption path).
5. Ollama narration of an approved plan (models already local: qwen3.6:27b),
   strictly outside the decision path, stored beside the seal.
6. Roles, approvals persistence, offline sync.
