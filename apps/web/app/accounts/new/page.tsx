import { redirect } from "next/navigation";

import { apiGet, type CurrentUser } from "../../../lib/api";
import NewAccountForm from "./new-account-form";

export const dynamic = "force-dynamic";

// UX guard only: the API refuses observers and anonymous callers regardless.
export default async function NewAccountPage() {
  const { body: me } = await apiGet<CurrentUser>("/api/v1/auth/me");
  if (me.role === "observer") {
    redirect("/accounts");
  }
  return <NewAccountForm />;
}
