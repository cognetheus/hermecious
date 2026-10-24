# Dry-run simulator contract (P4.5)

Decision record: [ADR-024](../adr/ADR-024-zero-egress-simulator.md). Code: `apps/api/app/simulations/`. UI: the "Dry run" section on `/campaigns/{id}`, and `/campaigns/{id}/simulations/{run_id}`.

> **SIMULATION ONLY — 0 real messages sent.** Every response, page and export carries this label. `real_messages_sent` is 0 by database constraint.

## Endpoints

All responses use `Cache-Control: no-store`. Other organizations get 404.

| Route | Roles | Behaviour |
|---|---|---|
| `POST /api/v1/campaigns/{cid}/simulations` | owner, operator (CSRF) | `{scenario?, max_items? (1–30, default 30), idempotency_key}`. Returns 201, or 200 on replay. 409 for a reused key with a different request, or **another active run on this campaign**. 422 for an unknown scenario, `max_items` over 30, or extra fields |
| `GET /api/v1/campaigns/{cid}/simulations` | any | Up to 50 runs, newest first |
| `GET /api/v1/campaigns/{cid}/simulations/{rid}` | any | The run, its `report`, `report_digest` and `items[]` |
| `POST /api/v1/campaigns/{cid}/simulations/{rid}/cancel` | owner, operator (CSRF) | A pending run is cancelled immediately, along with its job. A running run stops before its next item. A terminal run is returned unchanged |
| `GET /api/v1/campaigns/{cid}/simulations/{rid}/export.csv` | any | Redacted CSV: the label, run and digest lines, then `seq, account, decision, reasons, simulated_lifecycle, sim_receipt_id` |

Scenarios: `all_allow`, `opt_out_mid_run`, `quiet_hours`, `quota`, `stale_approval`, `provider_429_mock`, `transport_timeout_mock`, `worker_restart_mock`.

## Item

```json
{
  "seq": 1,
  "account": "Crescent Valley Grammar School (Synthetic)",
  "bucket": "accepted",
  "reasons": [],
  "lifecycle": "sim_delivered",
  "sim_receipt_id": "sim-3f1c…",
  "attempts": 1,
  "draft_revision": 2,
  "approval_id": "…",
  "permission_revision": {"id": "…", "version": 2},
  "next_window_at": null
}
```

- `bucket` is one of `accepted`, `denied`, `deferred` or `invalid`.
- `lifecycle` is one of `sim_delivered`, `sim_failed` or `not_attempted`.

## Sample synthetic report (clearly simulated)

From `test_sim_08` with the `quota` scenario: 32 synthetic accounts, bounded to 30.

```json
{
  "label": "SIMULATION ONLY — 0 real messages sent",
  "real_messages_sent": 0,
  "considered": 30,
  "buckets": {
    "accepted": {"count": 1, "denominator": 30, "percent": 3.3, "kind": "simulated"},
    "deferred": {"count": 1, "denominator": 30, "percent": 3.3, "kind": "simulated"},
    "denied":   {"count": "d", "denominator": 30, "kind": "simulated"},
    "invalid":  {"count": "i", "denominator": 30, "kind": "simulated"}
  },
  "lifecycle": {"sim_delivered": {"count": 1, "denominator": 1, "percent": 100.0, "kind": "simulated"}},
  "reconciled": true,
  "missing_prerequisites": {"campaign membership": "…", "contact on record": "…"},
  "standing_blockers": [
    "official WhatsApp template approval (P5; fixtures are simulation only)",
    "real 30-school evidence-quality audit (P3.4 EVAL-07)",
    "verified real opt-in evidence for real contacts"
  ]
}
```

**Reconciliation:** `accepted + denied + deferred + invalid = considered = 30` (here d + i = 28), and `sim_delivered + sim_failed = accepted`.
