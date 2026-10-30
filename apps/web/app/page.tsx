import Link from "next/link";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { apiInternalUrl, type CurrentUser } from "../lib/api";
import LogoutButton from "./logout-button";

// UX guard only: the API enforces authentication on every request.
export const dynamic = "force-dynamic";

async function currentUser(): Promise<CurrentUser | null> {
  const cookieHeader = (await cookies()).toString();
  const response = await fetch(`${apiInternalUrl()}/api/v1/auth/me`, {
    headers: cookieHeader ? { cookie: cookieHeader } : {},
    cache: "no-store",
  });
  if (response.status === 401) {
    return null;
  }
  if (!response.ok) {
    throw new Error(`session check failed with status ${response.status}`);
  }
  return (await response.json()) as CurrentUser;
}

export default async function HomePage() {
  const user = await currentUser();
  if (user === null) {
    redirect("/login");
  }
  return (
    <main>
      <h1>Hermecious</h1>
      <p>
        Signed in as {user.display_name ?? user.email} ({user.role})
      </p>
      <p>
        <Link href="/accounts">Accounts</Link> · <Link href="/discovery">Discovery</Link> · <Link href="/quality">Evidence quality</Link> · <Link href="/campaigns">Campaigns</Link> · <Link href="/offers">Offers</Link> · <Link href="/integrations/whatsapp">WhatsApp test</Link>
      </p>
      <LogoutButton />
    </main>
  );
}
