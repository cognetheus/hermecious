import { karachiTime } from "../../../lib/accounts";
import { apiGet } from "../../../lib/api";
import { type AssessmentsResponse, DECISION_LABELS, DIMENSION_LABELS } from "../../../lib/qualification";
import { AssessForm, OverrideForm } from "./qualification-actions";

type OfferSummary = { id: string; code: string; status: string; published_revision: number | null };

export default async function QualificationPanel({ accountId, canEdit }: { accountId: string; canEdit: boolean }) {
  const [assessments, offers] = await Promise.all([
    apiGet<AssessmentsResponse>(`/api/v1/accounts/${accountId}/assessments`),
    apiGet<{ offers: OfferSummary[] }>("/api/v1/offers"),
  ]);
  const data = assessments.status === 200 ? assessments.body : null;
  const latest = data?.latest ?? null;
  const published = offers.status === 200 ? offers.body.offers.filter((o) => o.status === "published") : [];
  const offerCode = latest?.offer_id ? published.find((o) => o.id === latest.offer_id)?.code ?? "offer no longer published" : null;
  return (
    <section aria-labelledby="qualification">
      <h2 id="qualification">Qualification</h2>
      <p>
        Four separate ordinal judgements from cited evidence (strong, moderate, weak, unknown). Unknown means no
        evidence yet, not a negative. There is no score or probability, and no recommendation here sends, enrolls or
        schedules anything.
      </p>
      {canEdit ? <AssessForm accountId={accountId} offers={published} /> : null}
      {data?.needs_reassessment && latest ? (
        <p role="note">Evidence, rights or the offer changed since this assessment: assess again.</p>
      ) : null}
      {latest ? (
        <div>
          <p role="status">
            <strong>{DECISION_LABELS[latest.decision]}</strong>
          </p>
          <p>
            {latest.origin === "override" ? `Reviewer override (machine said: ${latest.machine_decision.replace("_", " ")}). Reason: ${latest.override_reason}` : latest.decision_text}
          </p>
          <p>
            Revision {latest.revision}, {latest.rubric_version}
            {offerCode ? `; offer ${offerCode} (${latest.capability_version ?? "unpublished"})` : "; no published offer"}; channel
            eligibility: not checked; assessed {karachiTime(latest.created_at)}
          </p>
          {latest.blocking.length > 0 ? (
            <p>Not a contact candidate yet because: {latest.blocking.join("; ")}.</p>
          ) : null}
          {(Object.keys(DIMENSION_LABELS) as (keyof typeof DIMENSION_LABELS)[]).map((key) => {
            const dim = latest.dimensions[key];
            return (
              <article key={key} aria-label={`Dimension ${DIMENSION_LABELS[key]}`}>
                <h3>
                  {DIMENSION_LABELS[key]}: {dim.value}
                  {dim.value !== dim.machine_value ? ` (reviewer; rubric said ${dim.machine_value})` : ""}
                </h3>
                <p>{dim.reason}</p>
                {dim.fact_ids.length > 0 ? <p>Cited facts: {dim.fact_ids.length}</p> : <p>No cited facts.</p>}
              </article>
            );
          })}
          {latest.questions.length > 0 ? (
            <div>
              <h3>Open questions</h3>
              <ul>
                {latest.questions.map((q) => (
                  <li key={q}>{q}</li>
                ))}
              </ul>
            </div>
          ) : null}
          {canEdit ? <OverrideForm accountId={accountId} assessment={latest} /> : null}
          <h3>Assessment history</h3>
          <ol reversed aria-label="Assessment history">
            {data?.history.map((h) => (
              <li key={h.id}>
                Revision {h.revision} ({h.origin}): {h.decision.replace("_", " ")}
                {h.changed_fields.length > 0 ? `; changed ${h.changed_fields.join(", ")}` : ""}
                {h.override_reason ? `; reason: ${h.override_reason}` : ""}; {karachiTime(h.created_at)}
              </li>
            ))}
          </ol>
        </div>
      ) : (
        <p>Not assessed yet.</p>
      )}
    </section>
  );
}
