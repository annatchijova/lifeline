# Bundled synthetic incident-room demo

These artifacts are a sealed, synthetic flood scenario included so every clone
opens with a working incident-room experience. They are not live operational
data and must never be treated as one.

They were generated from the versioned scenario and declared what-if variants:

```bash
python3 -m lifeline plan scenarios/flood_v1.json --out web/demo \
  --reference-time 2026-07-17T11:00:00Z --no-trace
python3 -m lifeline simulate scenarios/flood_v1.json scenarios/flood_v1_whatifs.json \
  --out web/demo --reference-time 2026-07-17T11:00:00Z
```

`room.html` opens this bundle by default. `room.html?mode=live` reads only the
caller-generated `out/` artifacts and is the path that can use the local,
hash-chained approvals API.
