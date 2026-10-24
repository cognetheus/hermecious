import Link from "next/link";
import { notFound } from "next/navigation";

import { apiGet, type CurrentUser } from "../../../lib/api";
import {
  type AccountDetail,
  describeValue,
  type Fact,
  karachiTime,
  verificationLabel,
} from "../../../lib/accounts";
import AccountEditor from "./account-editor";
import CorrectionForm from "./correction-form";
import EvidenceForm from "./evidence-form";
import ResearchSection from "./research";
import SchoolSignalsSection from "./school-signals";

export const dynamic = "force-dynamic";

function FactCard({ fact, canEdit, accountId }: { fact: Fact; canEdit: boolean; accountId: string }) {
  return (
    <article aria-label={`${fact.claim_type} fact`}>
      <h4>
        {fact.claim_type}: {describeValue(fact.value)}
      </h4>
      <p>
        <strong>{verificationLabel(fact)}</strong>; confidence {fact.confidence_label}; observed{" "}
        {karachiTime(fact.observed_at)} (Asia/Karachi)
        {fact.expires_at ? `; expires ${karachiTime(fact.expires_at)}` : ""}
      </p>
      {fact.source ? (
        <p>
          Source: {fact.source.provider} <code>{fact.source.source_url}</code> ({fact.source.permitted_storage_class},{" "}
          {fact.source.rights_policy_version}); observed {karachiTime(fact.source.observed_at)}
          {fact.source.expires_at ? `; source expires ${karachiTime(fact.source.expires_at)}` : ""}
        </p>
      ) : (
        <p>No source: this is not verified evidence.</p>
      )}
      {fact.evidence_excerpt ? <blockquote>{fact.evidence_excerpt}</blockquote> : null}
      {fact.correction_reason ? <p>Correction reason: {fact.correction_reason}</p> : null}
      {canEdit && fact.is_current ? <CorrectionForm accountId={accountId} fact={fact} /> : null}
    </article>
  );
}

export default async function AccountPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const [{ body: me }, response] = await Promise.all([
    apiGet<CurrentUser>("/api/v1/auth/me"),
    apiGet<AccountDetail>(`/api/v1/accounts/${encodeURIComponent(id)}`),
  ]);
  if (response.status === 404 || response.status === 422) {
    notFound();
  }
  const account = response.body;
  const canEdit = me.role !== "observer" && account.status !== "excluded";
  const current = account.facts.filter((f) => f.is_current);
  const supported = current.filter((f) => f.verification_status === "source_supported");
  const hypotheses = current.filter((f) => f.verification_status !== "source_supported");
  const history = account.facts.filter((f) => !f.is_current);
  const sources = Array.from(
    new Map(account.facts.filter((f) => f.source).map((f) => [f.source!.id, f.source!])).values(),
  );

  return (
    <main>
      <p>
        <Link href="/accounts">All accounts</Link>
      </p>
      <h1>{account.canonical_name}</h1>
      <section aria-labelledby="identity">
        <h2 id="identity">Identity</h2>
        <p>
          {account.city}
          {account.locality ? `, ${account.locality}` : ""}; status <strong>{account.status}</strong>; version{" "}
          {account.version}; updated {karachiTime(account.updated_at)}
        </p>
        {account.aliases.length > 0 ? <p>Aliases: {account.aliases.join(", ")}</p> : null}
        {canEdit || me.role === "owner" ? (
          <AccountEditor account={account} role={me.role} />
        ) : null}
      </section>

      <section aria-labelledby="evidence">
        <h2 id="evidence">Evidence (current, source-supported)</h2>
        {supported.length === 0 ? <p>No source-supported facts yet. Absence of evidence is not evidence of absence.</p> : null}
        {supported.map((fact) => (
          <FactCard key={fact.id} fact={fact} canEdit={canEdit} accountId={account.id} />
        ))}
      </section>

      <section aria-labelledby="hypotheses">
        <h2 id="hypotheses">Hypotheses and unknowns (not verified)</h2>
        {hypotheses.length === 0 ? <p>None.</p> : null}
        {hypotheses.map((fact) => (
          <FactCard key={fact.id} fact={fact} canEdit={canEdit} accountId={account.id} />
        ))}
      </section>

      <section aria-labelledby="corrections">
        <h2 id="corrections">Correction history</h2>
        {history.length === 0 ? <p>No corrections.</p> : null}
        {history.map((fact) => (
          <article key={fact.id} aria-label="superseded fact">
            <p>
              Superseded: {fact.claim_type}: {describeValue(fact.value)} ({verificationLabel(fact)}, observed{" "}
              {karachiTime(fact.observed_at)}) → replaced by fact {fact.superseded_by_fact_id}
            </p>
          </article>
        ))}
      </section>

      <ResearchSection accountId={account.id} canEdit={canEdit} />

      <SchoolSignalsSection accountId={account.id} canEdit={canEdit} />

      {canEdit ? <EvidenceForm accountId={account.id} sources={sources} /> : null}

      <section aria-labelledby="audit">
        <h2 id="audit">Audit trail</h2>
        <ul>
          {account.audits.map((audit, index) => (
            <li key={`${audit.recorded_at}-${index}`}>
              {karachiTime(audit.recorded_at)}: {audit.action_type} by {audit.actor_user_id}
            </li>
          ))}
        </ul>
      </section>
    </main>
  );
}
