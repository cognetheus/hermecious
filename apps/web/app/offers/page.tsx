import Link from "next/link";

import { apiGet } from "../../lib/api";
import type { OfferSummary } from "../../lib/offers";

export const dynamic = "force-dynamic";

export default async function OffersPage() {
  const { body } = await apiGet<{ offers: OfferSummary[] }>("/api/v1/offers");
  return (
    <main>
      <p>
        <Link href="/">Home</Link>
      </p>
      <h1>Offers</h1>
      {body.offers.length === 0 ? (
        <p>No offers yet.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Code</th>
              <th>Audience</th>
              <th>Status</th>
              <th>Published revision</th>
              <th>Draft revision</th>
            </tr>
          </thead>
          <tbody>
            {body.offers.map((offer) => (
              <tr key={offer.id}>
                <td>
                  <Link href={`/offers/${offer.id}`}>{offer.code}</Link>
                </td>
                <td>{offer.audience}</td>
                <td>{offer.status}</td>
                <td>{offer.published_revision ?? "none"}</td>
                <td>{offer.current_draft_revision ?? "none"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}
