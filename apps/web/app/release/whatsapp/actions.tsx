"use client";

import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { errorMessage, postJson } from "../../../lib/mutate";
import { ATTESTATION_KINDS } from "../../../lib/release";

const BASE = "/api/v1/release/whatsapp";

function useAction() {
  const router = useRouter();
  const [message, setMessage] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  async function run(path: string, body: unknown, done: string) {
    setPending(true);
    try {
      const result = await postJson(`${BASE}${path}`, body);
      setMessage(result.ok ? done : errorMessage(result.data));
      router.refresh();
    } finally {
      setPending(false);
    }
  }
  const status = (
    <span role="status" aria-live="polite">
      {message}
    </span>
  );
  return { run, pending, status };
}

export function Evaluate() {
  const { run, pending, status } = useAction();
  return (
    <p>
      <button type="button" disabled={pending} onClick={() => run("/readiness/evaluate", {}, "Assessment recorded (nothing was sent)")}>
        Evaluate readiness now
      </button>{" "}
      {status}
    </p>
  );
}

export function AttestForm() {
  const { run, pending, status } = useAction();
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    await run("/attestations", { kind: form.get("kind"), statement: form.get("statement"), evidence_ref: form.get("evidence") }, "Attestation recorded");
  }
  return (
    <form onSubmit={submit} aria-label="Record an attestation">
      <label>
        Decision{" "}
        <select name="kind">
          {ATTESTATION_KINDS.map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </label>{" "}
      <label>
        Statement <input name="statement" required minLength={20} maxLength={1000} size={50} />
      </label>{" "}
      <label>
        Evidence reference <input name="evidence" required minLength={10} maxLength={500} size={30} />
      </label>{" "}
      <button type="submit" disabled={pending}>
        Record attestation
      </button>{" "}
      {status}
    </form>
  );
}

export function AuthorizeForm({ assessmentId, acknowledgement }: { assessmentId: string; acknowledgement: string }) {
  const { run, pending, status } = useAction();
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    await run(
      "/pilot",
      {
        assessment_id: assessmentId,
        acknowledgement: form.get("ack"),
        purpose: form.get("purpose"),
        max_per_day: Number(form.get("cap")),
        days: Number(form.get("days")),
      },
      "Pilot authorized (it still sends nothing by itself)",
    );
  }
  return (
    <form onSubmit={submit} aria-label="Authorize a pilot">
      <p>
        Type exactly: <q>{acknowledgement}</q>
      </p>
      <label>
        Acknowledgement <input name="ack" required size={70} autoComplete="off" />
      </label>
      <br />
      <label>
        Purpose{" "}
        <select name="purpose">
          <option value="marketing">marketing</option>
          <option value="utility">utility</option>
        </select>
      </label>{" "}
      <label>
        Messages a day <input name="cap" type="number" min={1} max={3} defaultValue={1} required />
      </label>{" "}
      <label>
        Days <input name="days" type="number" min={1} max={14} defaultValue={7} required />
      </label>{" "}
      <button type="submit" disabled={pending}>
        Authorize pilot
      </button>{" "}
      {status}
    </form>
  );
}

export function AuthorizationActions({ id, status: current }: { id: string; status: string }) {
  const { run, pending, status } = useAction();
  return (
    <>
      {" "}
      {current === "active" ? (
        <>
          <button type="button" disabled={pending} onClick={() => run(`/pilot/${id}/pause`, { reason: "human_takeover" }, "Paused (human takeover)")}>
            Pause: human takeover
          </button>{" "}
          <button type="button" disabled={pending} onClick={() => run(`/pilot/${id}/pause`, { reason: "quality_alert" }, "Paused (quality alert)")}>
            Pause: quality alert
          </button>{" "}
        </>
      ) : (
        <button type="button" disabled={pending} onClick={() => run(`/pilot/${id}/resume`, {}, "Resumed")}>
          Resume
        </button>
      )}{" "}
      <button type="button" disabled={pending} onClick={() => run(`/pilot/${id}/revoke`, {}, "Revoked")}>
        Revoke
      </button>{" "}
      {status}
    </>
  );
}
