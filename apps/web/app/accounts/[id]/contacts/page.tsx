import Link from "next/link";
import { notFound } from "next/navigation";

import { karachiTime } from "../../../../lib/accounts";
import { apiGet, type CurrentUser } from "../../../../lib/api";
import type { CampaignSummary } from "../../../../lib/campaigns";
import { ELIGIBILITY_NOTICE, type ContactView, type PolicyInfo } from "../../../../lib/contacts";
import { AddContact, Evaluate, PermissionActions, RecordEvidence, Suppress } from "./actions";

export const dynamic = "force-dynamic";

export default async function ContactsPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const [{ body: me }, contacts, { body: policy }, { body: campaigns }] = await Promise.all([
    apiGet<CurrentUser>("/api/v1/auth/me"),
    apiGet<{ items: ContactView[] }>(`/api/v1/accounts/${encodeURIComponent(id)}/contacts`),
    apiGet<PolicyInfo>("/api/v1/channel-eligibility/policy"),
    apiGet<{ items: CampaignSummary[] }>("/api/v1/campaigns"),
  ]);
  if (contacts.status === 404 || contacts.status === 422) notFound();
  const canEdit = me.role !== "observer";
  const isOwner = me.role === "owner";
  return (
    <main>
      <p>
        <Link href={`/accounts/${id}`}>Back to account</Link>
      </p>
      <h1>Contacts and channel eligibility</h1>
      <p role="alert" style={{ fontSize: "1.4rem", fontWeight: 700, border: "3px solid currentColor", padding: "0.5rem" }}>
        {ELIGIBILITY_NOTICE}
      </p>
      <p>
        A public phone number is not permission, research priority is not consent, and an inbound message is not a
        marketing opt-in. Opt-in evidence starts as pending; only an owner who did not record it can verify it. A
        decision is a reading at one moment ({policy.policy_version}), never an authorization to send.
      </p>
      {canEdit ? <AddContact accountId={id} /> : null}
      {contacts.body.items.length === 0 ? <p>No contacts yet.</p> : null}
      {contacts.body.items.map((contact) => (
        <article key={contact.id} aria-label={`Contact ${contact.address}`}>
          <h2>
            {contact.address} ({contact.role.replaceAll("_", " ")}, {contact.channel})
          </h2>
          <p role="status">
            {contact.suppressed && contact.suppression
              ? `Suppressed (${contact.suppression.reason.replaceAll("_", " ")}) since ${karachiTime(contact.suppression.created_at)} — overrides every campaign`
              : "Not suppressed"}
          </p>
          <table>
            <caption>Permission evidence</caption>
            <thead>
              <tr>
                <th scope="col">Purpose</th>
                <th scope="col">Status</th>
                <th scope="col">Evidence</th>
                <th scope="col">Recorded</th>
                <th scope="col">Review</th>
                <th scope="col">Expires</th>
                {canEdit ? <th scope="col">Actions</th> : null}
              </tr>
            </thead>
            <tbody>
              {contact.permissions.map((p) => (
                <tr key={p.id}>
                  <td>{p.purpose}</td>
                  <td>
                    {p.status} (v{p.version})
                  </td>
                  <td>
                    {p.capture_method
                      ? `${p.capture_method.replaceAll("_", " ")}; ${p.consent_wording_version}; ${p.business_name}; proof ${p.proof?.kind} ${p.proof?.hint ?? ""} (${p.proof?.reference}); captured ${karachiTime(p.captured_at ?? null)}`
                      : "restricted"}
                  </td>
                  <td>{p.recorded_at ? `${karachiTime(p.recorded_at)} by ${p.recorded_by ?? "unknown"}` : "restricted"}</td>
                  <td>
                    {p.reviewed_by ? `${p.status === "rejected" ? "rejected" : "verified"} by ${p.reviewed_by} at ${karachiTime(p.reviewed_at ?? null)}: ${p.review_reason}` : null}
                    {p.revoked_by ? ` revoked by ${p.revoked_by} at ${karachiTime(p.revoked_at ?? null)}: ${p.revoke_reason}` : null}
                  </td>
                  <td>{karachiTime(p.expires_at)}</td>
                  {canEdit ? (
                    <td>
                      <PermissionActions contactId={contact.id} permission={p} isOwner={isOwner} />
                    </td>
                  ) : null}
                </tr>
              ))}
            </tbody>
          </table>
          {canEdit ? (
            <>
              <RecordEvidence contactId={contact.id} wording={policy.consent_wording} businessName={policy.business_name} />
              {contact.suppressed ? null : <Suppress contactId={contact.id} />}
              <Evaluate contactId={contact.id} campaigns={campaigns.items} fixtures={policy.fixtures} />
            </>
          ) : null}
        </article>
      ))}
    </main>
  );
}
