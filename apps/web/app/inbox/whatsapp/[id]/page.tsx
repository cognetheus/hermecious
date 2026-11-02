import Link from "next/link";
import { notFound } from "next/navigation";

import { karachiTime } from "../../../../lib/accounts";
import { apiGet } from "../../../../lib/api";
import { CONTENT_LABEL, deliveryText, READ_ONLY_LABEL, type Timeline } from "../../../../lib/inbox";
import { AutoRefresh, MarkReviewed } from "../actions";

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
