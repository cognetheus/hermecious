import Link from "next/link";
import { notFound } from "next/navigation";

import { karachiTime } from "../../../../../lib/accounts";
import { apiGet, type CurrentUser } from "../../../../../lib/api";
import { safeHttpsUrl } from "../../../../../lib/discovery";
import type { ContactView, PolicyInfo } from "../../../../../lib/contacts";
import { approvalLabel, DRAFT_NOTICE, type DraftView, type ReviewReceipt } from "../../../../../lib/drafts";
import { EditDraft, GenerateDraft, RegenerateDraft, ReviewDraft } from "./actions";

export const dynamic = "force-dynamic";

export default async function DraftStudio({ params }: { params: Promise<{ id: string; accountId: string }> }) {
  const { id, accountId } = await params;
  const [{ body: me }, drafts, contacts, { body: policy }] = await Promise.all([
    apiGet<CurrentUser>("/api/v1/auth/me"),
    apiGet<{ items: DraftView[] }>(`/api/v1/campaigns/${encodeURIComponent(id)}/accounts/${encodeURIComponent(accountId)}/drafts`),
    apiGet<{ items: ContactView[] }>(`/api/v1/accounts/${encodeURIComponent(accountId)}/contacts`),
    apiGet<PolicyInfo>("/api/v1/channel-eligibility/policy"),
  ]);
  if (drafts.status === 404 || drafts.status === 422) notFound();
  const canEdit = me.role !== "observer";
  const [latest, ...older] = drafts.body.items;
  const history = latest
    ? await apiGet<{ items: ReviewReceipt[] }>(`/api/v1/drafts/${encodeURIComponent(latest.id)}/reviews`)
    : null;
  const contactOptions = (contacts.status === 200 ? contacts.body.items : []).map((c) => ({ id: c.id, address: c.address, suppressed: c.suppressed }));
  const addressOf = new Map(contactOptions.map((c) => [c.id, c.address]));
  const liveApproval = latest?.approval.state === "approved_content" || latest?.approval.state === "approval_stale" ? latest.approval.review?.id ?? null : null;
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
          <p>
            Content digest <code>{latest.content_digest.slice(0, 12)}</code> · {latest.origin === "edited" ? "edited by a person" : "generated"}
          </p>
          {canEdit ? <RegenerateDraft draftId={latest.id} /> : null}
          {canEdit ? <EditDraft key={latest.id} draftId={latest.id} revision={latest.revision} body={latest.body_text} /> : null}
          <section aria-label="Content approval">
            <h3>
              Content approval <span style={{ border: "1px solid currentColor", padding: "0 0.3rem" }}>Simulation only</span>
            </h3>
            <p role="status">{approvalLabel(latest.approval)}</p>
            {latest.approval.review ? (
              <p>
                Last decision: {latest.approval.review.decision.replaceAll("_", " ")} by {latest.approval.review.reviewer ?? "unknown"} at{" "}
                {karachiTime(latest.approval.review.reviewed_at)}: {latest.approval.review.reason}
                {latest.approval.review.contact_id ? ` · contact ${addressOf.get(latest.approval.review.contact_id) ?? "masked"}` : ""}
                {latest.approval.review.template_ref ? ` · template ${latest.approval.review.template_ref}` : ""}
                {latest.approval.review.expires_at ? ` · expires ${karachiTime(latest.approval.review.expires_at)}` : ""}
              </p>
            ) : null}
            <p>Approval is content authorization only. It is not consent, not queued, not sent and not a WhatsApp template approval.</p>
            {canEdit ? (
              <ReviewDraft key={`${latest.id}-${latest.approval.review?.id ?? "none"}`} draftId={latest.id} digest={latest.content_digest} contacts={contactOptions} templates={policy.fixtures.templates} approvalId={liveApproval} />
            ) : null}
            {history && history.body.items.length > 0 ? (
              <ol aria-label="Review history" reversed>
                {history.body.items.map((r) => (
                  <li key={r.id}>
                    {r.decision.replaceAll("_", " ")} (revision {r.draft_revision}) by {r.reviewer ?? "unknown"} at {karachiTime(r.reviewed_at)}: {r.reason}
                  </li>
                ))}
              </ol>
            ) : null}
          </section>
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
                Revision {d.revision} ({d.origin}), {karachiTime(d.created_at)}: {d.status}; approval: {d.approval.state.replaceAll("_", " ")}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </main>
  );
}
