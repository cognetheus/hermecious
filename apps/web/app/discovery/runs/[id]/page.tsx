import Link from "next/link";
import { notFound } from "next/navigation";

import { karachiTime } from "../../../../lib/accounts";
import { apiGet, type CurrentUser } from "../../../../lib/api";
import { ACTIVE, reasonText, type Run, type RunCandidate, safeHttpsUrl, statusLabel } from "../../../../lib/discovery";
import { CancelRun, MatchActions, ReviewActions, RunRefresher } from "./run-actions";

export const dynamic = "force-dynamic";

function Candidate({ item, runId, canEdit }: { item: RunCandidate; runId: string; canEdit: boolean }) {
  const link = safeHttpsUrl(item.source_url);
  return (
    <article aria-label={`Listing ${item.display_name}`}>
      <h3 lang="und">{item.display_name}</h3>
      {item.name_local ? (
        <p>
          Local-script name: <span lang="ur" dir="rtl">{item.name_local}</span>
        </p>
      ) : null}
      <p>
        <strong>Unverified listing</strong>; review: {item.review_status}
        {item.account_id ? (
          <>
            {" "}
            (<Link href={`/accounts/${item.account_id}`}>open account</Link>)
          </>
        ) : null}
      </p>
      <p>
        {item.city}, {item.locality ?? "locality unknown"}
        {item.location_precision === "area_center" ? "; map point is an area centre, not an address" : ""}
      </p>
      <p>
        Source: {item.provider} <code>{item.external_key}</code>
        {link ? (
          <>
            {" "}
            (<a href={link} rel="noopener noreferrer nofollow" target="_blank">source record</a>)
          </>
        ) : (
          " (no source link)"
        )}
        ; observed {karachiTime(item.observed_at)} (Asia/Karachi)
        {item.upstream_timestamp ? `; upstream data as of ${karachiTime(item.upstream_timestamp)}` : ""}; rights{" "}
        {item.rights_policy_version}
        {item.expires_at ? `; ${item.expired ? "EXPIRED" : "expires"} ${karachiTime(item.expires_at)}` : ""}
      </p>
      {item.attribution ? <p>{item.attribution}</p> : null}
      <p>Unknown (not researched): {item.unknowns.join(", ")}.</p>
      {item.matches.length > 0 ? (
        <section aria-label={`Possible matches for ${item.display_name}`}>
          <h4>Possible same campus (needs a human decision)</h4>
          <ul>
            {item.matches.map((m) => (
              <li key={m.suggestion_id}>
                {m.counterpart_kind === "account" ? "Account" : "Listing"} “{m.counterpart_name ?? m.counterpart_id}”:{" "}
                {m.resolution === "suggest_review" ? "possible match" : "not enough evidence"} (
                {m.reason_codes.map(reasonText).join("; ")}); status {m.status}
                {canEdit ? <MatchActions match={m} /> : null}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      {canEdit ? <ReviewActions runId={runId} item={item} /> : null}
    </article>
  );
}

export default async function RunPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const path = `/api/v1/discovery/runs/${encodeURIComponent(id)}`;
  const [{ body: me }, response, candidates] = await Promise.all([
    apiGet<CurrentUser>("/api/v1/auth/me"),
    apiGet<Run>(path),
    apiGet<{ items: RunCandidate[] }>(`${path}/candidates`),
  ]);
  if (response.status === 404 || response.status === 422) {
    notFound();
  }
  const run = response.body;
  const canEdit = me.role !== "observer";
  const items = candidates.status === 200 ? candidates.body.items : [];
  const active = ACTIVE.includes(run.status);
  return (
    <main>
      <p>
        <Link href="/discovery">All discovery runs</Link>
      </p>
      <h1>Discovery run</h1>
      {run.synthetic ? <p>Synthetic fixture data: fictional records, not real Lahore schools.</p> : null}
      <p role="status" aria-live="polite">
        Status: {statusLabel(run)}
        {run.cancel_requested && active ? " (cancellation requested)" : ""}
      </p>
      {active ? <RunRefresher /> : null}
      <dl>
        <dt>Source and area</dt>
        <dd>
          {run.provider}; {run.area_label}; rights {run.rights_policy_version}
        </dd>
        <dt>Counts</dt>
        <dd>
          examined {run.examined_count}; staged {run.staged_count}; rejected by rules {run.rejected_count}; shown{" "}
          {run.displayed_count} (maximum {run.budget.max_candidates})
        </dd>
        <dt>Review</dt>
        <dd>
          {run.review_counts.accepted} accepted; {run.review_counts.rejected} rejected; {run.review_counts.deferred}{" "}
          deferred; {run.review_counts.pending} pending
        </dd>
        <dt>Times (Asia/Karachi)</dt>
        <dd>
          created {karachiTime(run.created_at)}; started {karachiTime(run.started_at)}; finished{" "}
          {karachiTime(run.finished_at)}
        </dd>
      </dl>
      <p>This run is bounded and is not a complete list of schools in {run.city}.</p>
      {run.attribution ? <p>{run.attribution}</p> : null}
      {canEdit && active ? <CancelRun runId={run.id} /> : null}
      <h2>Listings ({items.length})</h2>
      {items.length === 0 ? (
        <p>{active ? "Waiting for the worker…" : "No listings were found by this bounded run."}</p>
      ) : (
        items.map((item) => <Candidate key={item.candidate_id} item={item} runId={run.id} canEdit={canEdit} />)
      )}
    </main>
  );
}
