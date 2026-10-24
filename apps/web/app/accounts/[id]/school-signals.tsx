import { karachiTime } from "../../../lib/accounts";
import { apiGet } from "../../../lib/api";
import { safeHttpsUrl } from "../../../lib/discovery";
import { type Citation, KEY_LABELS, type Signal, type SignalsResponse, STATE_LABELS } from "../../../lib/signals";
import GenerateBrief from "./school-signals-actions";

function CitationItem({ id, citation }: { id: string; citation: Citation | undefined }) {
  if (!citation) return <li>fact {id}</li>;
  const link = safeHttpsUrl(citation.source?.source_url ?? null);
  return (
    <li>
      {citation.claim_type} ({citation.verification_status}
      {citation.superseded ? ", since corrected" : ""}), observed {karachiTime(citation.observed_at)}
      {citation.source ? (
        <>
          {"; "}
          {citation.source.provider}
          {link ? (
            <>
              {" "}
              <a href={link} rel="noopener noreferrer nofollow" target="_blank">
                {link}
              </a>
            </>
          ) : null}
          {citation.source.expired ? " (source rights expired)" : ""}
        </>
      ) : null}
    </li>
  );
}

function SignalCard({ signal, citations }: { signal: Signal; citations: Record<string, Citation> }) {
  const cited = signal.state === "conflicting" ? signal.conflicting_fact_ids : signal.fact_ids;
  return (
    <article aria-label={`Signal ${KEY_LABELS[signal.key] ?? signal.key}`}>
      <h3>{KEY_LABELS[signal.key] ?? signal.key}</h3>
      <p>
        <strong>{STATE_LABELS[signal.state]}</strong>
        {signal.freshness !== "none" ? `; evidence ${signal.freshness}` : ""}
        {signal.evidence_at ? `, as of ${karachiTime(signal.evidence_at)}` : ""}
      </p>
      <p>{signal.statement}</p>
      <p>
        <em>{signal.caveat}</em>
      </p>
      {cited.length > 0 ? (
        <ul aria-label="Citations">
          {cited.map((id) => (
            <CitationItem key={id} id={id} citation={citations[id]} />
          ))}
        </ul>
      ) : null}
      {signal.stale_fact_ids.length > 0 ? <p>{signal.stale_fact_ids.length} earlier fact(s) need checking again.</p> : null}
      <p>Discovery question: {signal.question}</p>
    </article>
  );
}

export default async function SchoolSignalsSection({ accountId, canEdit }: { accountId: string; canEdit: boolean }) {
  const response = await apiGet<SignalsResponse>(`/api/v1/accounts/${accountId}/school-signals`);
  const data = response.status === 200 ? response.body : null;
  const latest = data?.latest ?? null;
  return (
    <section aria-labelledby="school-research">
      <h2 id="school-research">School Research</h2>
      <p>
        A cautious brief from cited, current facts only. It describes what sources say publicly; it does not score,
        rank or qualify this school, and anything without evidence stays unknown.
      </p>
      {canEdit ? <GenerateBrief accountId={accountId} /> : null}
      {data?.needs_reassessment && latest ? (
        <p role="note">Evidence has changed since this brief was generated: generate it again to reassess.</p>
      ) : null}
      {latest ? (
        <div>
          <p>
            Brief {latest.rubric_version}, generated {karachiTime(latest.created_at)}
            {data && data.history.length > 1 ? `; ${data.history.length} versions kept` : ""}
          </p>
          {Object.values(latest.signals).map((signal) => (
            <SignalCard key={signal.key} signal={signal} citations={latest.citations} />
          ))}
        </div>
      ) : (
        <p>No brief has been generated yet.</p>
      )}
    </section>
  );
}
