"use client";

import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

const MESSAGES: Record<number, string> = {
  429: "Too many attempts. Try again later.",
  503: "Sign-in is temporarily unavailable. Try again shortly.",
};

export default function LoginPage() {
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const router = useRouter();

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setPending(true);
    setError(null);
    try {
      const response = await fetch("/api/v1/auth/login", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: form.get("email"), password: form.get("password") }),
      });
      if (response.ok) {
        router.replace("/");
        router.refresh();
        return;
      }
      setError(MESSAGES[response.status] ?? "Invalid email or password.");
    } catch {
      setError("Could not reach the server.");
    } finally {
      setPending(false);
    }
  }

  return (
    <main>
      <h1>Sign in to Hermecious</h1>
      <form onSubmit={onSubmit}>
        <label>
          Email
          <input name="email" type="email" autoComplete="username" required maxLength={320} />
        </label>
        <label>
          Password
          <input name="password" type="password" autoComplete="current-password" required maxLength={256} />
        </label>
        <button type="submit" disabled={pending}>
          {pending ? "Signing in…" : "Sign in"}
        </button>
        {error !== null && <p role="alert">{error}</p>}
      </form>
    </main>
  );
}
