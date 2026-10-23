"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

export default function LogoutButton() {
  const [pending, setPending] = useState(false);
  const router = useRouter();

  async function logout() {
    setPending(true);
    try {
      // The CSRF token is fetched on demand and kept only in memory.
      const csrf = await fetch("/api/v1/auth/csrf", { credentials: "same-origin", cache: "no-store" });
      if (csrf.ok) {
        const { csrf_token: token } = (await csrf.json()) as { csrf_token: string };
        await fetch("/api/v1/auth/logout", {
          method: "POST",
          credentials: "same-origin",
          headers: { "X-CSRF-Token": token },
        });
      }
    } finally {
      router.replace("/login");
      router.refresh();
    }
  }

  return (
    <button type="button" onClick={logout} disabled={pending}>
      {pending ? "Signing out…" : "Sign out"}
    </button>
  );
}
