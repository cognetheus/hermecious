import { describeValue, karachiTime } from "../../../lib/accounts";
import { apiGet } from "../../../lib/api";
import { safeHttpsUrl } from "../../../lib/discovery";
import { type ResearchClaim, type ResearchRun, type ResearchSource, runStatusText } from "../../../lib/research";
import { CancelResearch, ClaimReview, ResearchRefresher, StartResearch } from "./research-actions";

function Claim({ claim, canEdit }: { claim: ResearchClaim; canEdit: boolean }) {
  const link = safeHttpsUrl(claim.source.source_url);
  const label = claim.status === "accepted" ? "Accepted by a reviewer (now a fact)" : claim.status === "rejected" ? "Rejected" : "Proposed (not verified)";
  return (
    <article aria-label={`Research claim ${claim.claim_type}`}>
      <h4>
        {claim.claim_type}: {describeValue(claim.value)}
      </h4>
      <p>
        <strong>{label}</strong>; rule {claim.rule_id} ({claim.extractor_version}); language {claim.language}
      </p>
      {claim.excerpt ? (
        <blockquote lang={claim.language === "en" ? "en" : "ur"} dir={claim.language === "ur" ? "rtl" : "auto"}>
          {claim.excerpt}
        </blockquote>
      ) : claim.excerpt_withheld_reason ? (
        <p>Excerpt withheld: {claim.excerpt_withheld_reason}.</p>
      ) : (
        <p>
          No excerpt stored (source rights allow derived facts only); cited text is at characters {claim.locator.start}–
          {claim.locator.end}.
        </p>
      )}
      <p>
        Source: {claim.source.provider}
        {link ? (
          <>
            {" "}
            <a href={link} rel="noopener noreferrer nofollow" target="_blank">
              {link}
            </a>
          </>
        ) : null}{" "}
        ({claim.source.storage_class}, {claim.source.rights_policy_version}); captured {karachiTime(claim.source.observed_at)}
        {claim.source.expires_at ? `; rights until ${karachiTime(claim.source.expires_at)}` : ""}
        {claim.source.current_rights && claim.source.current_rights !== "ok" ? ` (stale: ${claim.source.current_rights})` : ""}
      </p>
      {claim.review_reason ? <p>Review note: {claim.review_reason}</p> : null}
      {canEdit && claim.status === "proposed" ? <ClaimReview claim={claim} /> : null}
    </article>
  );
}

export default async function ResearchSection({ accountId, canEdit }: { accountId: string; canEdit: boolean }) {
  const [sources, runs] = await Promise.all([
    apiGet<{ items: ResearchSource[]; max_sources: number }>(`/api/v1/accounts/${accountId}/research-sources`),
    apiGet<{ items: ResearchRun[] }>(`/api/v1/accounts/${accountId}/research-runs`),
  ]);
  const latest = runs.status === 200 ? runs.body.items[0] : undefined;
  const detail = latest ? (await apiGet<ResearchRun>(`/api/v1/research-runs/${latest.id}`)).body : undefined;
  const active = detail ? detail.status === "pending" || detail.status === "running" : false;
  const items = sources.status === 200 ? sources.body.items : [];
  return (
    <section aria-labelledby="research">
      <h2 id="research">Research (proposed claims need review)</h2>
      <p>
        Research reads only sources already tied to this account, at most {sources.status === 200 ? sources.body.max_sources : 5} per
        run. A proposed claim repeats what a source says; it is not a verified fact until a reviewer accepts it, and
        a missing statement is never evidence of absence.
      </p>
      {canEdit ? <StartResearch accountId={accountId} sources={items} /> : null}
      {items.length === 0 ? <p>No sources are associated with this account yet.</p> : null}
      {detail ? (
        <div>
          <h3>Latest research run</h3>
          <p role="status" aria-live="polite">
            {runStatusText(detail)}; {detail.claims_abstained} statement(s) skipped as negated, instruction-like or
            over budget; started {karachiTime(detail.created_at)}
          </p>
          {active ? <ResearchRefresher /> : null}
          {canEdit && active ? <CancelResearch runId={detail.id} /> : null}
          <ul>
            {(detail.observations ?? []).map((o) => (
              <li key={o.source.id}>
                {o.source.provider}: {o.status}
                {o.reason_code ? ` (${o.reason_code})` : ""}
                {o.language ? `; language ${o.language}` : ""}
              </li>
            ))}
          </ul>
          {(detail.claims ?? []).map((claim) => (
            <Claim key={claim.id} claim={claim} canEdit={canEdit} />
          ))}
        </div>
      ) : (
        <p>No research has been run for this account.</p>
      )}
    </section>
  );
}
