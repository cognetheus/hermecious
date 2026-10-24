import Link from "next/link";
import { notFound } from "next/navigation";

import { karachiTime } from "../../../../../lib/accounts";
import { apiGet, type CurrentUser } from "../../../../../lib/api";
import { safeHttpsUrl } from "../../../../../lib/discovery";
import { DRAFT_NOTICE, type DraftView } from "../../../../../lib/drafts";
import { GenerateDraft, RegenerateDraft } from "./actions";

export const dynamic = "force-dynamic";

export default async function DraftStudio({ params }: { params: Promise<{ id: string; accountId: string }> }) {
  const { id, accountId } = await params;
  const [{ body: me }, drafts] = await Promise.all([
    apiGet<CurrentUser>("/api/v1/auth/me"),
    apiGet<{ items: DraftView[] }>(`/api/v1/campaigns/${encodeURIComponent(id)}/accounts/${encodeURIComponent(accountId)}/drafts`),
  ]);
  if (drafts.status === 404 || drafts.status === 422) notFound();
  const canEdit = me.role !== "observer";
  const [latest, ...older] = drafts.body.items;
  return (
    <main>
      <p>
        <Link href={`/campaigns/${id}`}>Back to campaign</Link> · <Link href={`/accounts/${accountId}`}>Account</Link>
      </p>
      <h1>Draft Studio</h1>
      <p role="alert" style={{ fontSize: "1.4rem", fontWeight: 700, border: "3px solid currentColor", padding: "0.5rem" }}>
        {DRAFT_NOTICE}
      </p>
      <p>
        Drafts repeat only cited, current facts and the published offer&apos;s approved claims. Channel permission is not
        checked, and nothing on this page sends, approves, queues or schedules a message.
      </p>
      {canEdit ? <GenerateDraft campaignId={id} accountId={accountId} /> : null}
      {latest ? (
        <article aria-label="Latest draft">
          <h2>
            Revision {latest.revision} ({latest.template_id}, {latest.locale}) — {latest.status === "blocked_stale" ? "BLOCKED: stale" : "needs review"}
          </h2>
          {latest.stale_reasons.length > 0 ? <p>Stale because: {latest.stale_reasons.join(", ")}. Regenerate after fixing the cause.</p> : null}
          {latest.mode === "fixture" ? <p>Fixture campaign: synthetic test data.</p> : null}
          <pre style={{ whiteSpace: "pre-wrap" }}>{latest.body_text}</pre>
          <table>
            <caption>Evidence behind each sentence</caption>
            <thead>
              <tr>
                <th scope="col">Sentence</th>
                <th scope="col">Kind</th>
                <th scope="col">Grounding</th>
              </tr>
            </thead>
            <tbody>
              {latest.sentences.map((s, index) => {
                const link = safeHttpsUrl(s.source?.source_url ?? null);
                return (
                  <tr key={index}>
                    <td>{s.text}</td>
                    <td>{s.category}</td>
                    <td>
                      {s.grounding.fact_id ? `fact ${s.grounding.fact_id}` : null}
                      {s.source ? (
                        <>
                          {"; "}
                          {s.source.provider} ({s.source.rights_policy_version}
                          {s.source.rights_current ? "" : ", rights expired"})
                          {link ? (
                            <>
                              {" "}
                              <a href={link} rel="noopener noreferrer nofollow" target="_blank">
                                source
                              </a>
                            </>
                          ) : null}
                        </>
                      ) : null}
                      {s.grounding.capability_code ? `offer claim ${s.grounding.capability_code} (${s.grounding.capability_version})` : null}
                      {s.grounding.signal_key ? `discovery question for ${s.grounding.signal_key}` : null}
                      {Object.keys(s.grounding).length === 0 ? "reviewed template text" : null}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {canEdit ? <RegenerateDraft draftId={latest.id} /> : null}
        </article>
      ) : (
        <p>No draft yet.</p>
      )}
      {older.length > 0 ? (
        <section aria-label="Earlier revisions">
          <h2>Earlier revisions (kept unchanged)</h2>
          <ul>
            {older.map((d) => (
              <li key={d.id}>
                Revision {d.revision}, {karachiTime(d.created_at)}: {d.status}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </main>
  );
}
