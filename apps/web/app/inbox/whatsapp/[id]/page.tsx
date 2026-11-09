import Link from "next/link";
import { notFound } from "next/navigation";

import { karachiTime } from "../../../../lib/accounts";
import { apiGet, type CurrentUser } from "../../../../lib/api";
import {
  AUTO_REPLIES_LABEL,
  CONTENT_LABEL,
  deliveryText,
  type Intent,
  type Ownership,
  READ_ONLY_LABEL,
  type ReplyProposalView,
  type Timeline,
  words,
} from "../../../../lib/inbox";
import { AutoRefresh, IntentReview, MarkReviewed, OwnershipControls, RejectProposal, SuggestReply } from "../actions";

function ReplySuggestion({ messageId, lineage, mode }: { messageId: string; lineage: ReplyProposalView[]; mode: string }) {
  const latest = lineage[0];
  const p = latest?.proposal;
  const state = !latest ? null : latest.stale ? "STALE" : p?.status === "proposed" ? latest.label : "ABSTAINED";
  return (
    <section aria-label="Suggested reply" style={{ borderLeft: "3px dashed currentColor", paddingLeft: "0.5rem" }}>
      {mode === "off" ? (
        <p>Reply suggestions are disabled until the P6.1 intent gate is verified.</p>
      ) : (
        <SuggestReply messageId={messageId} label={latest ? "Suggest again" : "Suggest a reply"} />
      )}
      {latest && p ? (
        <>
          <p>
            <strong>{state}</strong> · version {latest.version} · human review required · suggested next step: {words(p.recommended_action)}
            {latest.rejected ? ` · rejected: ${latest.rejected.reason}` : ""}
          </p>
          {p.proposed_reply ? (
            <blockquote dir="auto" style={{ whiteSpace: "pre-wrap" }}>
              {p.proposed_reply}
            </blockquote>
          ) : (
            <p>No draft: {p.abstention_codes.map(words).join(", ")}</p>
          )}
          {p.language_fallback ? <p>The message was not in English; approved wording exists only in English, so a person must adapt it.</p> : null}
          {p.missing_claims.length > 0 ? <p>No approved claim for: {p.missing_claims.map(words).join(", ")}</p> : null}
          {p.citations.length > 0 ? (
            <ul aria-label="Citations">
              {p.citations.map((c) => (
                <li key={`${c.key}-${c.sentence}`}>
                  {words(c.kind)} {c.key} · digest {c.digest.slice(0, 12)} · offer revision {p.snapshot.offer_revision}
                </li>
              ))}
            </ul>
          ) : null}
          {p.confirmed_facts.length > 0 ? (
            <ul aria-label="Stated by the correspondent (unverified)">
              {p.confirmed_facts.map((f) => (
                <li key={f.code} dir="auto">
                  {words(f.code)}: <q>{f.text}</q> (stated, not verified)
                </li>
              ))}
            </ul>
          ) : null}
          <p>
            <small>
              {p.composer_version} · rules only, no model · nothing here is sent
            </small>
          </p>
          {!latest.rejected && p.status === "proposed" ? <RejectProposal messageId={messageId} proposalId={latest.id} /> : null}
        </>
      ) : null}
    </section>
  );
}

function OwnershipPanel({
  ownership,
  assignees,
  isOwner,
}: {
  ownership: Ownership;
  assignees: { id: string; name: string }[];
  isOwner: boolean;
}) {
  const o = ownership;
  const owner = o.owner_type === "human" ? (o.owner ?? "a person") : o.owner_type === "agent" ? "agent (released by a person)" : "nobody yet";
  return (
    <section aria-label="Ownership" style={{ border: "1px solid currentColor", padding: "0.5rem" }}>
      <p role="note" style={{ fontWeight: 700 }}>
        {AUTO_REPLIES_LABEL}
      </p>
      <p>
        Owner: <strong>{owner}</strong> · state <strong>{words(o.state)}</strong> · generation {o.owner_generation} · revision{" "}
        {o.revision}
      </p>
      {o.handoff ? (
        <p aria-label="Handoff task">
          Handoff ({o.handoff.status}
          {o.handoff.urgency === "high" ? ", urgent" : ""}): {words(o.handoff.reason)}
          {o.handoff.assigned_to ? ` · assigned to ${o.handoff.assigned_to}` : " · unassigned"} · since{" "}
          {karachiTime(o.handoff.created_at)}
        </p>
      ) : null}
      <OwnershipControls threadId={o.thread_id} revision={o.revision} assignees={assignees} isOwner={isOwner} />
      {o.attempts.length > 0 ? (
        <ul aria-label="Dispatch attempts">
          {o.attempts.map((a) => (
            <li key={a.id}>
              {words(a.state)}
              {a.deny_reason ? ` (${words(a.deny_reason)})` : ""} · generation {a.queued_generation}
              {a.submitted_before_takeover ? " · submitted before the takeover (cannot be recalled)" : ""}
            </li>
          ))}
        </ul>
      ) : null}
      {o.history.length > 0 ? (
        <details>
          <summary>Ownership history ({o.history.length})</summary>
          <ol aria-label="Ownership history">
            {o.history.map((h) => (
              <li key={`${h.generation}-${h.at}-${h.command}`}>
                {words(h.command)} · {words(h.from)} → {words(h.to)} · {words(h.reason)} · by {h.actor ?? "unknown"} ·{" "}
                {karachiTime(h.at)}
                {h.canceled_attempts > 0 ? ` · ${h.canceled_attempts} queued attempt(s) cancelled` : ""}
              </li>
            ))}
          </ol>
        </details>
      ) : null}
    </section>
  );
}

function IntentNote({ messageId, intent }: { messageId: string; intent: Intent }) {
  return (
    <section aria-label="Intent for review" style={{ borderLeft: "3px solid currentColor", paddingLeft: "0.5rem" }}>
      <p>
        Intent (for review): <strong>{words(intent.primary_intent)}</strong>
        {intent.secondary_intents.length > 0 ? ` · also ${intent.secondary_intents.map(words).join(", ")}` : ""} · confidence{" "}
        {intent.confidence} · {words(intent.language)} · suggested next step: {words(intent.recommended_action)} (nothing happens
        automatically)
      </p>
      {intent.safety_flags.length > 0 ? <p role="alert">Flags: {intent.safety_flags.map(words).join(", ")}</p> : null}
      {intent.evidence.length > 0 ? (
        <p>
          Because of:{" "}
          {intent.evidence.map((e) => (
            <q key={`${e.start}-${e.reason}`} dir="auto">
              {e.text}
            </q>
          ))}
        </p>
      ) : null}
      <p>
        <small>
          {intent.notice} Classifier {intent.classifier_version}
          {intent.model_version ? ` · model ${intent.model_version}` : " · rules only, no model"}
        </small>
      </p>
      {intent.review ? (
        <p>
          Reviewed: {intent.review.decision}
          {intent.review.corrected_primary ? ` as ${words(intent.review.corrected_primary)}` : ""}
          {intent.review.note ? ` · ${intent.review.note}` : ""}
        </p>
      ) : (
        <IntentReview messageId={messageId} observationId={intent.observation_id} />
      )}
    </section>
  );
}

export const dynamic = "force-dynamic";

export default async function Conversation({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ before?: string }>;
}) {
  const [{ id }, { before }] = await Promise.all([params, searchParams]);
  const query = before ? `?before=${encodeURIComponent(before)}` : "";
  const { status, body } = await apiGet<Timeline>(`/api/v1/inbox/whatsapp/threads/${encodeURIComponent(id)}${query}`);
  if (status === 404 || status === 422) notFound();
  if (status === 403) {
    return (
      <main>
        <p role="alert">The inbox is available to owners and operators only.</p>
      </main>
    );
  }
  const { thread, entries } = body;
  const [ownership, staff, me] = await Promise.all([
    apiGet<Ownership>(`/api/v1/inbox/whatsapp/threads/${encodeURIComponent(thread.id)}/ownership`),
    apiGet<{ items: { id: string; name: string }[] }>("/api/v1/inbox/whatsapp/assignees"),
    apiGet<CurrentUser>("/api/v1/auth/me"),
  ]);
  return (
    <main>
      <AutoRefresh seconds={10} />
      <p>
        <Link href="/inbox/whatsapp">Back to inbox</Link>
      </p>
      <h1>{thread.party.label}</h1>
      <p role="note" style={{ fontWeight: 700, border: "2px solid currentColor", padding: "0.4rem" }}>
        {READ_ONLY_LABEL}
      </p>
      <p>
        {thread.party.address} · {thread.party.environment === "test" ? "TEST connection" : "production connection"}
        {thread.party.conflict ? " · this test number also matches a sourced contact; it is not mapped to that school" : ""}
        {thread.party.suppressed ? " · opted out (suppressed)" : ""} · times shown in Asia/Karachi
      </p>
      {ownership.status === 200 ? (
        <OwnershipPanel
          ownership={ownership.body}
          assignees={staff.status === 200 ? staff.body.items : []}
          isOwner={me.status === 200 && me.body.role === "owner"}
        />
      ) : null}
      {thread.party.type === "unmatched" ? (
        <p>This sender is not linked to any school or contact. Nothing is created or inferred from their messages.</p>
      ) : null}
      {thread.unread > 0 ? <MarkReviewed threadId={thread.id} throughSeq={thread.last_inbound_seq} /> : <p>All messages reviewed.</p>}
      {body.before_cursor ? (
        <p>
          <Link href={`/inbox/whatsapp/${thread.id}?before=${encodeURIComponent(body.before_cursor)}`}>Older messages</Link>
        </p>
      ) : null}
      <ol aria-label="Timeline">
        {entries.map((e) =>
          e.type === "inbound" ? (
            <li key={e.id} aria-label="Inbound message">
              <p>
                <strong>Inbound</strong> · {karachiTime(e.at)} · signed by Meta
                {e.seq > thread.reviewed_through_seq ? " · unread" : ""}
                {e.stop_signal ? " · opt-out request (suppressed automatically)" : ""}
              </p>
              {e.text !== null ? (
                <p dir="auto" style={{ whiteSpace: "pre-wrap", unicodeBidi: "plaintext" }}>
                  {e.text}
                  {e.truncated ? " …(truncated)" : ""}
                </p>
              ) : (
                <p>
                  <em>{CONTENT_LABEL[e.content]}</em>
                </p>
              )}
              {e.intent ? <IntentNote messageId={e.id} intent={e.intent} /> : null}
              {e.content !== "not_text" ? (
                <ReplySuggestion messageId={e.id} lineage={e.reply_proposals ?? []} mode={body.reply_mode ?? "off"} />
              ) : null}
            </li>
          ) : (
            <li key={e.id} aria-label="TEST outbound message">
              <p>
                <strong>TEST outbound</strong> · {karachiTime(e.at)} · template {e.template.name} ({e.template.language},{" "}
                {e.template.category}) · {e.state.replaceAll("_", " ")}
                {e.error_class ? ` · error: ${e.error_class}` : ""}
              </p>
              <p>Delivery: {deliveryText(e)}</p>
              {e.statuses.length > 0 ? (
                <ul aria-label="Signed webhook statuses">
                  {e.statuses.map((s) => (
                    <li key={`${s.status}-${s.at}`}>
                      {s.status} at {karachiTime(s.at)}
                      {s.error_code ? ` (error ${s.error_code})` : ""}
                    </li>
                  ))}
                </ul>
              ) : null}
            </li>
          ),
        )}
      </ol>
    </main>
  );
}
