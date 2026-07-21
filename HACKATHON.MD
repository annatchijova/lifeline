# LIFELINE — OpenAI Hackathon

This file is the practical submission and demo runbook for LIFELINE. It is a
research and hackathon prototype using synthetic data only; it has not been
used in real incidents and is not an emergency service.

## Submission and session references

- `genial`: `019f6fec-10f8-78d2-b060-c96c3ed6a718`
- LIFELINE session: `019f704c-b199-7df0-92d3-1a8d82beafa1`
- LIFELINE session: `019f6dd0-45f4-7821-b831-ed252199d449`
- LIFELINE session: `019f72b1-aaf8-7832-9652-74795b424ac2`

## Public judge links

- [LIFELINE landing page](https://lifeline-openai-hackathon.vercel.app/index.html)
- [Sealed synthetic flood-map demo](https://lifeline-openai-hackathon.vercel.app/room.html?mode=demo)
- [Demo fallback path](https://lifeline-openai-hackathon.vercel.app/room.html?mode=demo&missing=live)
- [Operations-console interface](https://lifeline-openai-hackathon.vercel.app/ops.html)

The hosted site is deliberately static and demo-only. The map’s approve/reject
buttons are local browser interactions; they never dispatch a resource or
write an approval. The hosted operations page is useful to inspect the
interface, but its authenticated incident backend runs only on a local
loopback server.

## How to review the public demo

1. Open the landing page. It separates the synthetic judge demo, a local
   sealed export, and local operations.
2. Open the synthetic flood-map demo. Inspect the briefing, map, proposals,
   validator findings, Verification Graph, alternatives, and local-only human
   approval controls.
3. Open the fallback URL. It deliberately demonstrates that the bundled sealed
   synthetic demo remains available when no local export is present.
4. Open the operations-console link to see the interface used for the real
   local workflow. Do not enter a real credential on the public hosted site:
   it has no deployed incident API by design.

## How to run the complete local workflow

From the repository root:

```bash
python3 -m lifeline plan scenarios/flood_v1.json \
  --out out \
  --reference-time 2026-07-17T11:00:00Z

python3 -m lifeline operator init --out out --id demo-admin
# Save the token printed once by this command.

python3 -m lifeline serve --out out --port 8094
```

Then open `http://127.0.0.1:8094/web/ops.html`.

1. Paste the locally generated token and select **Connect**.
2. Under **Create a validated incident**, choose
   `scenarios/flood_v1.json` and select **Create incident**.
3. Select the incident, then choose **Compute sealed plan**.
4. Use **Fill template** under **Append or correct a report** to append a
   report or create a correction. Each accepted operation creates a new,
   hash-linked revision; it never edits history silently.
5. Recompute the sealed plan. Inspect the verification outcome, attention
   feed, and any human approval controls in the local room.
6. Verify the local evidence and ledger after the walkthrough:

```bash
python3 -m lifeline verify --out out
```

## Optional OpenAI controlled reading guide

OpenAI is optional and never enters planning, validation, approval, alerting,
or dispatch. After a normal local export, set an API key only in the local
process environment and run:

```bash
export OPENAI_API_KEY="..."
python3 -m lifeline narrate --out out --model gpt-5
python3 -m lifeline verify --out out
```

LIFELINE verifies the sealed plan and Verification Graph before provider
egress. OpenAI receives a minimal, read-only packet and can return only opaque
citation selections. LIFELINE renders every visible sentence locally from
sealed values and fixed templates, then seals that controlled briefing against
the exact plan and verification hashes. The provider has no mutation, approval,
alert, or dispatch tool.

For the complete contract and threat boundary, read
[`docs/AGENT_BRIEFING_MODE.md`](docs/AGENT_BRIEFING_MODE.md).
