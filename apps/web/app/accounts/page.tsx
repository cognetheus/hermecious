import Link from "next/link";

import { apiGet, type CurrentUser } from "../../lib/api";
import { type Account, STATUSES } from "../../lib/accounts";

export const dynamic = "force-dynamic";

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

function one(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

export default async function AccountsPage({ searchParams }: { searchParams: SearchParams }) {
  const params = await searchParams;
  const status = one(params.status);
  const q = one(params.q);
  const cursor = one(params.cursor);
  const query = new URLSearchParams();
  if (status) query.set("status", status);
  if (q) query.set("q", q);
  if (cursor) query.set("cursor", cursor);
  const [{ body: me }, list] = await Promise.all([
    apiGet<CurrentUser>("/api/v1/auth/me"),
    apiGet<{ accounts: Account[]; next_cursor: string | null; error?: { message: string } }>(
      `/api/v1/accounts?${query.toString()}`,
    ),
  ]);
  const filters = new URLSearchParams();
  if (status) filters.set("status", status);
  if (q) filters.set("q", q);

  return (
    <main>
      <p>
        <Link href="/">Home</Link>
      </p>
      <h1>Accounts</h1>
      {me.role !== "observer" ? (
        <p>
          <Link href="/accounts/new">New account</Link>
        </p>
      ) : null}
      <form method="get" aria-label="Filter accounts">
        <label>
          Status{" "}
          <select name="status" defaultValue={status ?? ""}>
            <option value="">Any</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>{" "}
        <label>
          Name starts with <input name="q" defaultValue={q ?? ""} maxLength={100} />
        </label>{" "}
        <button type="submit">Apply filters</button>
      </form>
      {list.status !== 200 ? (
        <p role="alert">{list.body.error?.message ?? "Could not load accounts"}</p>
      ) : list.body.accounts.length === 0 ? (
        <p>No accounts match.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th scope="col">Name</th>
              <th scope="col">Locality</th>
              <th scope="col">City</th>
              <th scope="col">Status</th>
            </tr>
          </thead>
          <tbody>
            {list.body.accounts.map((account) => (
              <tr key={account.id}>
                <td>
                  <Link href={`/accounts/${account.id}`}>{account.canonical_name}</Link>
                </td>
                <td>{account.locality ?? "unknown"}</td>
                <td>{account.city}</td>
                <td>{account.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {list.status === 200 && list.body.next_cursor ? (
        <p>
          <Link href={`/accounts?${new URLSearchParams([...filters, ["cursor", list.body.next_cursor]]).toString()}`}>
            Next page
          </Link>
        </p>
      ) : null}
    </main>
  );
}
