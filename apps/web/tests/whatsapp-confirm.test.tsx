// @vitest-environment jsdom
// P5.3 (WAAD-08, P5.3.4): the owner-confirmed test-send dialog. The API is faked at `fetch`; the component is real.
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PreviewForm } from "../app/integrations/whatsapp/actions";
import { REAL_SEND_LABEL, type Template, type TestRecipient } from "../lib/whatsapp";

vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn() }) }));

const TEMPLATE: Template = {
  id: "tpl-row-1",
  template_id: "900000000000001",
  name: "hermecious_test_ping",
  language: "en_US",
  category: "UTILITY",
  provider_status: "APPROVED",
  supported: true,
  body_text: "Hello {{1}}, this is a Hermecious test message.",
  body_parameter_count: 1,
  header_parameter_count: 0,
  fetched_at: "2026-10-23T07:00:00+00:00",
  fresh: true,
  usable_for_test: true,
};
const RECIPIENT: TestRecipient = { id: "rcp-1", label: "Owner's own phone", address: "+92 ••••••• 201", status: "active" };
const PREVIEW = {
  id: "send-1",
  state: "awaiting_confirmation",
  delivery: null,
  created_at: "2026-10-23T07:00:00+00:00",
  real_message: true,
  label: REAL_SEND_LABEL,
  template: { name: "hermecious_test_ping", language: "en_US", category: "UTILITY" },
  parameters: ["Owner"],
  preview_text: "Hello Owner, this is a Hermecious test message.",
  recipient: "+92 ••••••• 201",
  preview_digest: "a".repeat(64),
  confirmation_nonce: "nonce-" + "b".repeat(40),
  replayed: false,
};

function fakeApi() {
  const calls: { url: string; body: unknown }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const body = init?.body ? JSON.parse(String(init.body)) : null;
      calls.push({ url, body });
      const json = url.endsWith("/auth/csrf")
        ? { csrf_token: "csrf" }
        : url.endsWith("/confirm")
          ? { ...PREVIEW, state: "provider_accepted", replayed: false }
          : PREVIEW;
      return new Response(JSON.stringify(json), { status: url.endsWith("/test-sends") ? 201 : 200 });
    }),
  );
  return calls;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

async function openPreview(canConfirm: boolean) {
  const calls = fakeApi();
  render(<PreviewForm templates={[TEMPLATE]} recipients={[RECIPIENT]} canConfirm={canConfirm} />);
  fireEvent.change(screen.getByLabelText(/Parameter/), { target: { value: "Owner" } });
  fireEvent.click(screen.getByRole("button", { name: "Preview test" }));
  await screen.findByRole("dialog");
  return calls;
}

describe("P5.3 confirmation dialog", () => {
  it("shows the exact REAL-message label, the masked number and the exact text, and sends only the digest and nonce", async () => {
    const calls = await openPreview(true);
    const dialog = screen.getByRole("dialog");
    expect(screen.getByRole("heading", { name: REAL_SEND_LABEL })).toBeTruthy();
    expect(dialog.textContent).toContain("+92 ••••••• 201");
    expect(dialog.textContent).toContain("Hello Owner, this is a Hermecious test message.");
    expect(dialog.textContent).not.toContain("920000000201");
    const send = screen.getByRole("button", { name: "Send one real test message" }) as HTMLButtonElement;
    expect(send.disabled).toBe(true); // nothing can be sent before the explicit acknowledgement
    fireEvent.click(screen.getByRole("checkbox"));
    expect(send.disabled).toBe(false);
    fireEvent.click(send);
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/send-1/confirm"))).toBe(true));
    const confirm = calls.find((c) => c.url.endsWith("/send-1/confirm"));
    expect(confirm?.body).toEqual({ preview_digest: PREVIEW.preview_digest, confirmation_nonce: PREVIEW.confirmation_nonce });
    const preview = calls.find((c) => c.url.endsWith("/test-sends"));
    expect(Object.keys(preview?.body as object).sort()).toEqual(["idempotency_key", "parameters", "recipient_id", "template_id"]);
  });

  it("gives an operator the preview but no way to send", async () => {
    await openPreview(false);
    expect(screen.getByText(/Only the owner can confirm this send/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Send one real test message" })).toBeNull();
  });
});
