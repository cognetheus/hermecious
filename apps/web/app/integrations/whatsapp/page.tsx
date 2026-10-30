import Link from "next/link";

import { karachiTime } from "../../../lib/accounts";
import { apiGet, type CurrentUser } from "../../../lib/api";
import {
  deliveryLabel,
  type ConnectionStatus,
  type Template,
  type TestRecipient,
  type TestSend,
} from "../../../lib/whatsapp";
import { PendingSendActions, PreviewForm, RecipientForm, RevokeRecipient, SyncTemplates } from "./actions";

export const dynamic = "force-dynamic";

// Diagnostics for the one guarded operator test send (P5.3). There is deliberately no control that sends to an
// account, contact or campaign, and no free-form recipient entry: numbers come from the server-side allowlist.
export default async function WhatsAppIntegrationPage() {
  const [{ body: me }, { body: status }, { body: catalog }, { body: recipients }, { body: sends }] = await Promise.all([
    apiGet<CurrentUser>("/api/v1/auth/me"),
    apiGet<ConnectionStatus>("/api/v1/integrations/whatsapp/connection"),
    apiGet<{ items: Template[] }>("/api/v1/integrations/whatsapp/templates"),
    apiGet<{ items: TestRecipient[] }>("/api/v1/integrations/whatsapp/test-recipients"),
    apiGet<{ items: TestSend[] }>("/api/v1/integrations/whatsapp/test-sends"),
  ]);
  const owner = me.role === "owner";
  const canPreview = me.role !== "observer" && status.test_sending_available && status.bound;
  const usable = catalog.items.filter((t) => t.usable_for_test);
  const active = recipients.items.filter((r) => r.status === "active");
  return (
    <main>
      <p>
        <Link href="/">Home</Link>
      </p>
      <h1>WhatsApp test connection</h1>
      <p role="note">
        Production outreach is off ({status.production_outreach}). This page can only send one approved template to a
        number the owner registered for testing.
      </p>
      <section aria-labelledby="connection">
        <h2 id="connection">Connection</h2>
        <ul aria-label="Connection status">
          <li>Mode: {status.mode}</li>
          <li>Graph API: {status.graph_version}</li>
          <li>
            Bound: {status.bound ? `yes (phone number ID ${status.phone_number_id})` : "no"}
            {status.bound && !status.matches_configuration ? " (does not match the server configuration)" : ""}
          </li>
          <li>Test sending: {status.test_sending_available ? (status.test_outbound_enabled ? "enabled" : "kill switch off") : "unavailable in this mode"}</li>
        </ul>
      </section>

      <section aria-labelledby="templates">
        <h2 id="templates">Templates (from Meta)</h2>
        {owner && status.test_sending_available && status.bound ? <SyncTemplates /> : null}
        {catalog.items.length === 0 ? (
          <p>No templates synced.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Language</th>
                <th>Category</th>
                <th>Meta status</th>
                <th>Fetched</th>
                <th>Usable for a test</th>
              </tr>
            </thead>
            <tbody>
              {catalog.items.map((t) => (
                <tr key={t.id}>
                  <td>{t.name}</td>
                  <td>{t.language}</td>
                  <td>{t.category}</td>
                  <td>{t.provider_status}</td>
                  <td>
                    {karachiTime(t.fetched_at)}
                    {t.fresh ? "" : " (stale)"}
                  </td>
                  <td>{t.usable_for_test ? "yes" : t.supported ? "no" : "no (unsupported components)"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section aria-labelledby="recipients">
        <h2 id="recipients">Test recipients</h2>
        {recipients.items.length === 0 ? (
          <p>No test recipients registered.</p>
        ) : (
          <ul aria-label="Test recipients">
            {recipients.items.map((r) => (
              <li key={r.id}>
                {r.label} · {r.address} · {r.status}
                {owner && r.status === "active" ? <RevokeRecipient id={r.id} /> : null}
              </li>
            ))}
          </ul>
        )}
        {owner && status.test_sending_available && status.bound ? <RecipientForm /> : null}
      </section>

      {canPreview ? (
        <section aria-labelledby="preview">
          <h2 id="preview">Preview a test message</h2>
          <PreviewForm templates={usable} recipients={active} canConfirm={owner} />
        </section>
      ) : null}

      <section aria-labelledby="sends">
        <h2 id="sends">Test messages</h2>
        {sends.items.length === 0 ? (
          <p>No test messages.</p>
        ) : (
          <ol aria-label="Test messages">
            {sends.items.map((s) => (
              <li key={s.id}>
                <p>
                  {karachiTime(s.created_at)} · {s.state.replaceAll("_", " ")} · delivery: {deliveryLabel(s.delivery)}
                  {s.template ? ` · ${s.template.name} (${s.template.language}, ${s.template.category}) to ${s.recipient}` : ""}
                  {s.denial_reason ? ` · denied: ${s.denial_reason}` : ""}
                  {s.error_class ? ` · error: ${s.error_class}` : ""}
                  {s.provider_message_id ? ` · Meta message ID ${s.provider_message_id}` : ""}
                </p>
                {s.timeline && s.timeline.length > 0 ? (
                  <ul aria-label="Webhook statuses">
                    {s.timeline.map((t) => (
                      <li key={`${t.status}-${t.provider_timestamp}`}>
                        {t.status} at {karachiTime(t.provider_timestamp)}
                        {t.error_code ? ` (error ${t.error_code})` : ""}
                      </li>
                    ))}
                  </ul>
                ) : null}
                {me.role !== "observer" ? <PendingSendActions send={s} owner={owner} /> : null}
              </li>
            ))}
          </ol>
        )}
      </section>
    </main>
  );
}
