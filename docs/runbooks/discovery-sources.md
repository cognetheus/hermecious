# Discovery sources runbook (P2.2)

Contract: [source-adapters.md](../contracts/source-adapters.md). Decision record: [ADR-013](../adr/ADR-013-osm-overpass-source-and-egress.md).

Discovery produces **unverified listings** (`discovery_candidates`, status `unreviewed`). It never creates accounts, contacts or messages. Review and admission arrive in P2.4.

## Fallback: import an operator seed list (CSV)

The owner can import a list their organization already holds, such as a directory you own or a list you typed yourself.

1. **Prepare a UTF-8 CSV** (Excel's "CSV UTF-8" is fine; a BOM is accepted):

   ```csv
   school_name,city,locality,source_reference,external_key
   Example School (replace),Lahore,Model Town,Directory 2026 p.12,
   ```

   - `city` must be `Lahore`.
   - `external_key` is optional. Without it, a key is derived from the row.
   - Limits: ≤500 rows and ≤256 KB.
   - Cells that start with `= + - @ |` are refused, so they can never run as formulas later.

2. **Post it as the owner.** In the browser session, call:

   ```http
   POST /api/v1/discovery/seed-imports
   {"source_label": "...", "permission_declaration": "where the list came from and why you may use it", "csv_text": "..."}
   ```

   The UI arrives in P2.4.

3. **Read the response.**
   - It reports accepted and rejected counts, and rejection reasons by **row number**. Row content is never echoed.
   - Re-posting the same file returns `replayed: true` and changes nothing.

## Live source: OpenStreetMap via Overpass (owner opt-in only)

This is **off by default**. Each step is the owner's decision.

1. **Review the terms.** Read, then record who reviewed them and when:
   - the ODbL and attribution guidelines: <https://www.openstreetmap.org/copyright> and <https://osmfoundation.org/wiki/Attribution_Guidelines>;
   - the OSMF API policy: <https://operations.osmfoundation.org/policies/api/>;
   - the **current** usage terms of `overpass-api.de`.

   Public Overpass is shared infrastructure. Run rarely; for repeated collection, use an offline extract.

2. **Choose a bounding box** (`south,west,north,east`, ≤0.6° per side) and write down where it came from. The citation is required. The app never derives a box from a place name.

3. **Run one bounded query with explicit settings.** Pass them on the command line, not in `.env`, so the source is never left enabled by accident:

   ```sh
   docker compose run --rm --no-deps \
     -e HERMECIOUS_OSM_ENABLED=true \
     -e HERMECIOUS_OSM_REVIEWED_BY="<who reviewed the terms>" \
     -e HERMECIOUS_OSM_REVIEWED_AT="2026-10-24T09:00:00+05:00" \
     -e HERMECIOUS_OSM_BBOX="<south,west,north,east>" \
     -e HERMECIOUS_OSM_BBOX_CITATION="<where the box came from>" \
     api python -m app.discovery.cli --organization <org-uuid> --provider osm_overpass_schools --confirm-live
   ```

   **What one run does:**
   - It makes at most 3 requests (one query, plus retries on 429/503/timeouts within the 60 s budget), and accepts at most 30 listings.
   - stderr shows `endpoint=… requests=N`.
   - The JSON report shows `stop_reason`, `truncated`, `partial`, counts and attribution.
   - It writes an audit row `discovery.source_run`.

4. **Read the report honestly.**
   - **`truncated: true`:** the box held more schools than one run takes.
   - **An empty result** is a real outcome; record it as one.
   - **In every case:** listings are map data and say nothing about ownership, size, software or interest.

## Running and reviewing discovery in the app (P2.4)

1. **Start a run.** Go to **Discovery → New discovery run**. Only permitted sources are listed. Choose a budget (≤30 listings), then **Start run**. The worker picks the run up; the page refreshes every 2 s.
2. **Read the result honestly.**
   - **"Completed (bounded run)"** means the bounded query finished. It never means every school was found.
   - **Partial or failed** states show their reason, such as `rate_limited`, `provider_disabled` or `worker_error`.
3. **Review each listing.**
   - Read its source link, times, rights and unknowns.
   - If it shows **"Possible same campus"**, decide **Same campus** or **Different campus** first. A new account cannot be created while that question is open.
   - Then choose **Accept as new campus** (one account, research pending), **Attach to confirmed account**, **Reject** or **Defer**.
4. **Cancel if needed.** Cancel a queued or running run from its page. Accounts already admitted are kept.

## Refusals and what they mean

| Message or reason | Meaning |
|---|---|
| `live providers need --confirm-live` | Safety flag missing |
| `provider_disabled` | OSM is not enabled or not fully configured |
| `provider_unreviewed` / `rights_review_expired` | The review is missing or older than 365 days. Review again |
| Settings error naming `HERMECIOUS_OSM_*` | Activation is incomplete or invalid (endpoint not allowlisted, box too big or implausible, naive timestamp) |
| `stop_reason: rate_limited` / `unavailable` | The endpoint pushed back. Wait (Retry-After is honoured); do not loop |
| `stop_reason: policy_revoked` | The provider was disabled during the run. Nothing further was stored |
| `stop_reason: response_too_large` | The response exceeded 1 MB. Use a smaller box |
| Run `failed: requester_not_permitted` | The requester was deactivated or lost write access before the worker ran |
| Accept refused: `…rights_expired` | The listing's provenance is past retention. Run discovery again for a fresh, permitted observation |
| Accept refused: "decide the possible same-campus match first" | Resolve the P2.3 suggestion shown on the card |

## Rollback

- **Stop OSM:** stop passing the `HERMECIOUS_OSM_*` variables; runs then fail closed before any request.
- **Keep the data:** stored candidates and provenance are organization-scoped and attributed; keep them for review.
- **Remove data only deliberately:** delete only after reviewing ODbL obligations, and never by downgrading migrations on a database you care about.
