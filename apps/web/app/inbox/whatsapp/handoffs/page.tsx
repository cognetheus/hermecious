import Link from "next/link";

import { karachiTime } from "../../../../lib/accounts";
import { apiGet } from "../../../../lib/api";
import { AUTO_REPLIES_LABEL, type HandoffItem, words } from "../../../../lib/inbox";
import { AutoRefresh } from "../actions";

export const dynamic = "force-dynamic";

/** P6.3: conversations waiting for a person (urgent first, then oldest). Masked: no message text. */
export default async function Handoffs() {
  const { status, body } = await apiGet<{ items: HandoffItem[] }>("/api/v1/inbox/whatsapp/handoffs");
  return (
    <main>
      <AutoRefresh seconds={15} />
      <p>
        <Link href="/inbox/whatsapp">Back to inbox</Link>
      </p>
      <h1>Handoff queue</h1>
      <p role="note" style={{ fontWeight: 700, border: "2px solid currentColor", padding: "0.4rem" }}>
        {AUTO_REPLIES_LABEL}
      </p>
      {status !== 200 ? (
        <p role="alert">The handoff queue could not be loaded (status {status}).</p>
      ) : body.items.length === 0 ? (
        <p>No conversation is waiting for a person.</p>
      ) : (
        <ul aria-label="Handoff tasks">
          {body.items.map((t) => (
            <li key={t.id}>
              <Link href={`/inbox/whatsapp/${t.thread_id}`}>{t.address}</Link> · {t.urgency === "high" ? "URGENT · " : ""}
              {words(t.reason)} · {t.status} · {t.assigned_to ? `assigned to ${t.assigned_to}` : "unassigned"} · since{" "}
              {karachiTime(t.created_at)} (Asia/Karachi)
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
