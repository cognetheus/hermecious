import Link from "next/link";
import { notFound } from "next/navigation";

import { apiGet, type CurrentUser } from "../../../lib/api";
import { editableContent, type OfferDetail, READINESS_LABEL, type Revision } from "../../../lib/offers";
import OfferActions from "./offer-actions";

export const dynamic = "force-dynamic";

function RevisionCard({ revision }: { revision: Revision }) {
  return (
    <section>
      <h3>
        Revision {revision.revision}: {revision.state}
      </h3>
      <p>
        Capability version {revision.capability_version}; digest <code>{revision.content_sha256}</code>
        {revision.published_at ? `; published ${revision.published_at}` : ""}
      </p>
      <table>
        <thead>
          <tr>
            <th>Capability</th>
            <th>Readiness</th>
            <th>Proposed for sale</th>
            <th>Summary</th>
            <th>Limitations</th>
            <th>Evidence</th>
          </tr>
        </thead>
        <tbody>
          {revision.capability_matrix.map((claim) => (
            <tr key={claim.capability_code}>
              <td>{claim.capability_code}</td>
              <td>{READINESS_LABEL[claim.readiness]}</td>
              <td>{claim.approved_for_sales ? "yes" : "no"}</td>
              <td>{claim.summary}</td>
              <td>{claim.limitations.join("; ") || "none"}</td>
              <td>{claim.evidence_refs.join(", ") || "none"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p>
        Pricing:{" "}
        {revision.price_rules.length === 0
          ? "pricing unavailable"
          : revision.price_rules.map((p) => `${p.code} ${p.currency} ${p.amount} ${p.unit}${p.approved ? "" : " (not approved)"}`).join("; ")}
      </p>
      <p>Exclusions: {revision.exclusions.join("; ") || "none"}</p>
    </section>
  );
}

export default async function OfferPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const [{ body: me }, offerResponse, salesResponse] = await Promise.all([
    apiGet<CurrentUser>("/api/v1/auth/me"),
    apiGet<OfferDetail>(`/api/v1/offers/${encodeURIComponent(id)}`),
    apiGet<unknown>(`/api/v1/offers/${encodeURIComponent(id)}/sales-ready`),
  ]);
  if (offerResponse.status === 404 || offerResponse.status === 422) {
    notFound();
  }
  const offer = offerResponse.body;
  const latest = offer.revisions.at(-1);
  return (
    <main>
      <p>
        <Link href="/offers">All offers</Link>
      </p>
      <h1>{offer.code}</h1>
      <p>
        {offer.audience}: status <strong>{offer.status}</strong> (version {offer.version})
      </p>
      <p>
        Sales-ready:{" "}
        {salesResponse.status === 200 ? `yes, revision ${offer.published_revision}` : "no published, sellable revision"}
      </p>
      <OfferActions
        offerId={offer.id}
        role={me.role}
        status={offer.status}
        version={offer.version}
        draftRevision={offer.current_draft_revision}
        initialContent={JSON.stringify(editableContent(latest), null, 2)}
      />
      <h2>Revisions</h2>
      {offer.revisions.length === 0 ? <p>No revisions visible.</p> : null}
      {[...offer.revisions].reverse().map((revision) => (
        <RevisionCard key={revision.id} revision={revision} />
      ))}
    </main>
  );
}
