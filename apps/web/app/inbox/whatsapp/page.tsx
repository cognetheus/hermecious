import Link from "next/link";

import { karachiTime } from "../../../lib/accounts";
import { apiGet } from "../../../lib/api";
import { READ_ONLY_LABEL, type Thread } from "../../../lib/inbox";
import { AutoRefresh } from "./actions";

export const dynamic = "force-dynamic";

export default async function WhatsAppInbox({ searchParams }: { searchParams: Promise<{ cursor?: string }> }) {
  const { cursor } = await searchParams;
  const query = cursor ? `?cursor=${encodeURIComponent(cursor)}` : "";
  const { status, body } = await apiGet<{ items: Thread[]; next_cursor: string | null }>(`/api/v1/inbox/whatsapp/threads${query}`);
  return (
    <main>
      <AutoRefresh seconds={15} />
      <p>
        <Link href="/">Home</Link>
      </p>
      <h1>Inbox · WhatsApp</h1>
      <p>
        <Link href="/inbox/whatsapp/handoffs">Handoff queue</Link>
      </p>
      <p role="note" style={{ fontWeight: 700, border: "2px solid currentColor", padding: "0.4rem" }}>
        {READ_ONLY_LABEL}
      </p>
      {status === 403 ? (
        <p role="alert">The inbox is available to owners and operators only.</p>
      ) : status !== 200 ? (
        <p role="alert">
          The inbox could not be loaded (status {status}). <Link href="/inbox/whatsapp">Retry</Link>
        </p>
      ) : body.items.length === 0 ? (
        <p>No WhatsApp conversations yet. Only signed messages received from Meta appear here.</p>
      ) : (
        <>
          <ul aria-label="Conversations">
            {body.items.map((t) => (
              <li key={t.id}>
                <Link href={`/inbox/whatsapp/${t.id}`}>{t.party.label}</Link> · {t.party.address}
                {t.party.environment === "test" ? " · TEST" : ""}
                {t.party.suppressed ? " · opted out" : ""} · last activity {karachiTime(t.last_activity_at)} (Asia/Karachi)
                {t.unread > 0 ? ` · ${t.unread} unread` : " · reviewed"}
              </li>
            ))}
          </ul>
          {body.next_cursor ? <Link href={`/inbox/whatsapp?cursor=${encodeURIComponent(body.next_cursor)}`}>Older conversations</Link> : null}
        </>
      )}
    </main>
  );
}
