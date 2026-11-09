# ADR-033: Conversation ownership, human takeover and the final-dispatch fence

- **Status:** Proposed — awaiting owner acceptance
- **Date:** 2026-11-09
- **Source:** the owner's P6.3 prompt; blueprint §4 P6.3 ("human takeover blocks all agent sends immediately, including previously queued sends").

## Context

- **No automated replies exist:** P6.2 drafts are never sent, and P6.5 is not started.
- **Other gates:** P6.1 is not verified, and P5.5 is NO_GO.
- **What P6.3 provides:** the authority model, plus the one fence that any future automated reply must pass. It does not add a send path.

## Decision

1. **One canonical owner per conversation (P5.4 thread)** (`conversation_owners`, migration 0028):
   - **Fields:**
     - `state`: new, agent_owned, human_owned, paused, blocked or resolved;
     - `owner_type`: none, agent or human;
     - `owner_user_id`;
     - `owner_generation`;
     - `revision`.
   - **Checks:**
     - a human owner is always named;
     - the state always matches the owner type.
   - **Database triggers:**
     - the generation can never decrease;
     - owner rows cannot be deleted;
     - events are append-only.
2. **Commands are human-only and atomic** (`app/conversations/service.command`):
   - **Commands:** takeover, assign, pause, block, resolve, release_to_agent, reopen, open_handoff and acknowledge_handoff.
   - **What every command carries:**
     - a reason from a fixed list;
     - an `expected_revision`, where a mismatch is a 409 telling the user to reload (never last-writer-wins);
     - an idempotency key: the same key and request return the recorded result, and a changed request is a 409.
   - **Who may issue them:**
     - only an interactive session (an actor with a session verifier); system, job, classifier and model actors are refused;
     - `block` and `reopen` are owner-only.
   - **Assignees:** must be active owners or operators in the same organization.
   - **One transaction locks the owner row `FOR UPDATE`, then:**
     - bumps `owner_generation` on any change of authority;
     - **cancels every queued dispatch attempt**;
     - appends the event;
     - writes the audit.
   - **Releasing to the agent** is explicit and grants nothing else.
3. **Handoff tasks:** at most one active (open or acknowledged) task per conversation, enforced by a partial unique index.
   - Each task records reason, urgency, assignee and status.
   - The context is a reference only (`thread:` / `inbound:` / `proposal:`); no message text is copied into the task.
4. **Final-dispatch fence** (`app/conversations/fence.py`, `dispatch-fence-1.0`):
   - **Transport:** attempts have `transport = 'simulation'`. P6.3 contains no transport; tests inject a fake one.
   - **`final_check`:** locks the owner `FOR SHARE` and the attempt `FOR UPDATE`. It then re-checks, in order:
     - the attempt is queued;
     - the agent owns the conversation;
     - the generation equals both the expected one and the one the attempt was queued under;
     - the draft is the current, unstale, unrejected P6.2 proposal;
     - a reply approval exists (there is no approval source before P6.5, so this denies by default);
     - P4.3 eligibility;
     - the kill switch;
     - the P5.5 live gate;
     - the connection.
   - **Allow** commits `submitting` *before* any network call.
   - **Ordering:**
     - a takeover that commits first means the attempt is denied or cancelled;
     - a final check that commits first means the attempt is shown as "submitted before the takeover", and it cannot be recalled.
   - **Timeouts:** a timeout is `indeterminate` and is never resubmitted.
5. **API and UI.**
   - **Routes:**
     - `GET/POST /api/v1/inbox/whatsapp/threads/{id}/ownership`. Owners and operators can command (with CSRF); observers can read. The body uses `extra=forbid`, so a forged `owner_generation` or tool call is a 422.
     - `GET …/handoffs`: the queue, masked, with no message text.
     - `GET …/assignees`.
   - **Thread page:**
     - an **AUTO REPLIES DISABLED** banner;
     - the owner, state, generation and revision;
     - the handoff task;
     - controls with a reason;
     - dispatch attempts;
     - the history.
   - **Handoff queue page:** `/inbox/whatsapp/handoffs`.

## Rollback

- **Code:** revert the code; downgrade 0028 drops the four tables.
- **Data that stays:** nothing else references these tables, and no send path depends on them, because none exists.
- **What can still happen:** the inbox, drafts and test sends keep working.

## Consequences

- P6.5 must enqueue through `fence.enqueue`, call `fence.final_check` immediately before any send, and replace `fence.APPROVAL` with a real P4.4-style reply approval.
- Until P6.5, the fence denies every attempt (`reply_not_approved`).
