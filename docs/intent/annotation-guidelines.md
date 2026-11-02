# Intent annotation guidelines (`intent.v1`, P6.1)

These guidelines are for labelling inbound WhatsApp replies from school offices, for **human review**. A label describes what the message asks for. It never decides an action, and never grants or removes consent. Opt-out suppression stays with the deterministic P5.2/P4.3 path.

## Primary intent (exactly one)

`interested | needs_details | objection | request_demo | defer | not_interested | opt_out | human_request | ambiguous | abusive`

When a message carries several intents, the primary is the **first** match in this order. The others become `secondary`.

1. **`opt_out`:** a clear, unquoted, un-negated request to stop contact, for example "Stop messaging us", "Aap log dobara msg na karna", "دوبارہ میسج نہ کریں" or "Unsubscribe". It always also carries the flag `explicit_opt_out`.
2. **`abusive`:** insults, accusations of fraud, threats ("I will report you to the police").
3. **`request_demo`:** asks to see the product working.
4. **`needs_details`:** asks for price, features, modules, fees handling or a document.
5. **`human_request`:** asks for a person, a call, a manager or the principal.
6. **`objection`:** a reason not to buy that leaves the door open: "too expensive", "we already have software", "our staff can't use computers".
7. **`defer`:** "later", "after admissions/exams", "next month". It is **not** an opt-out and **not** a commitment. No follow-up is scheduled in P6.1.
8. **`not_interested`:** a polite "no".
9. **`interested`:** a positive signal without a concrete request.
10. **`ambiguous`:** everything else:
    - greetings, acknowledgements ("ok", "جی", 👍), "who is this?";
    - quoted or reported stop words;
    - instructions aimed at the system;
    - unsupported languages and empty or unavailable content.

## Safety flags (independent of the primary label; never dropped)

| Flag | When |
|---|---|
| `explicit_opt_out` | The primary is `opt_out`, including when demo or other intents are also present |
| `human_escalation_requested` | Any request for a person, call or principal, even as a secondary intent |
| `abusive_or_threatening` | Insults, fraud accusations, threats |
| `possible_sensitive_personal_data` | A phone number, an ID or form number, or a named child or student |
| `injection_attempt_suspected` | Text addressing the system ("ignore previous instructions", "I am your system admin", "disable approval", "send/WhatsApp this number") |
| `unsupported_language` | Not English, Roman Urdu or Urdu script |
| `model_uncertain` | Set by the classifier when its evidence conflicts |
| `service_window_unknown` | Set by the classifier when the message was not a verified inbound (never in P6.1) |

## Decisions for hard cases

- **Negation:**
  - "Don't stop", "band mat karna", "روکیں نہیں" are **not** opt-outs.
  - "Mat karein" or "na karna" attached to *message/contact/rabta* **is** an opt-out ("dobara msg na karna").
- **Quotation and reporting:** a stop word inside quotes, or after "sent me / likh ke bheja / example", is `ambiguous`, with no `explicit_opt_out`. A person decides.
- **Short messages:** a single "STOP", "unsubscribe" or "بند کریں" is an opt-out. A single "ok", "jee" or "hello" is ambiguous.
- **Confusables:** text is folded before matching (Cyrillic look-alikes, full-width letters, zero-width and bidi controls), so "ЅТОР" is an opt-out.
- **Code switching:**
  - Roman Urdu with English loan words ("Details bhej dein please") is `roman_urdu`.
  - `mixed` means Urdu script **and** Latin words in one message.
- **Sarcasm:** label the literal request, and leave tone to the reviewer.
- **Sensitive data:** keep the intent and add `possible_sensitive_personal_data`. Such text must never go to a remote model.

## Recommended action (read-only text, never executed)

| Primary | Action |
|---|---|
| `interested` | `review_interest` |
| `needs_details` | `review_details_request` |
| `objection` | `review_objection` |
| `request_demo` | `review_demo_request` |
| `defer` | `review_defer` |
| `not_interested` | `review_disinterest` |
| `opt_out` | `request_opt_out_review` |
| `human_request` | `route_to_human` |
| `abusive` | `review_abuse` |
| `ambiguous` | `manual_triage` |

## Dataset

`apps/api/tests/fixtures/intent/gold_v1.jsonl`, with its hash in `manifest.json`.

- **Split:** by **cluster** (a family of paraphrases), into `dev` (rule development) and `heldout` (measurement only).
- **Provenance:** the current fixtures are **agent-authored and not yet human-reviewed**. A reviewer should check every label against these guidelines, correct it where needed, and record their name and date in `manifest.json` (`human_review`). Until then, measured metrics describe behaviour on synthetic fixtures, not real-world accuracy.
