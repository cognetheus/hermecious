"""The `reply.v1` contract (P6.2, ADR-032). A reviewable draft or an abstention; never a send instruction.

A proposal carries no recipient, tool, transport, consent, ownership or opportunity field, and the recommended action
comes from a fixed, non-executable allowlist. `confirmed_facts` keeps its upstream name but means only "the
correspondent stated this", quoted from one signed message. It is never independent verification.
"""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.intent.schema import Language, PrimaryIntent, SafetyFlag

SCHEMA_VERSION = "reply.v1"
MAX_REPLY_CHARS = 1000

Action = Literal[
    "review_draft",  # a grounded draft exists; a person reviews it
    "manual_review_missing_claim",  # something was asked that no current approved claim answers
    "human_handoff",  # the correspondent asked for a person
    "opt_out_review_no_reply",  # an explicit opt-out: do not reply; the P5.2/P4.3 path owns suppression
    "abuse_review_no_reply",
    "manual_triage",  # ambiguous, injection, sensitive, unsupported language or unavailable content
]
Abstention = Literal[
    "opt_out", "abusive", "injection_suspected", "human_requested", "sensitive_personal_data", "unsupported_language",
    "ambiguous_intent", "intent_missing", "content_unavailable", "unmatched_contact", "missing_approved_claim",
    "no_published_offer", "ungrounded_assertion", "input_too_long",
]  # fmt: skip


class InvalidProposal(ValueError):
    pass


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Citation(_Strict):
    kind: Literal["capability", "price_rule"]
    key: Annotated[str, Field(pattern=r"^[a-z0-9_]{2,60}$")]
    digest: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    sentence: Annotated[int, Field(ge=0, le=20)]


class StatedFact(_Strict):
    code: Literal["current_tool", "campus_count", "student_count", "decision_maker", "timing"]
    text: Annotated[str, Field(min_length=1, max_length=200)]
    message_id: str
    start: Annotated[int, Field(ge=0)]
    end: Annotated[int, Field(ge=1)]
    attribution: Literal["prospect_stated"]
    verified: Literal[False]


class Snapshot(_Strict):
    offer_id: str | None
    offer_revision: int | None
    content_sha256: str | None
    claims_digest: str
    locale: Literal["en"]


class ReplyProposal(_Strict):
    schema_version: Literal["reply.v1"]
    status: Literal["proposed", "abstained"]
    proposed_reply: Annotated[str, Field(max_length=MAX_REPLY_CHARS)] | None
    reply_language: Literal["en"] | None
    language_fallback: bool
    inbound_language: Language
    intent: PrimaryIntent
    intent_observation_id: str | None
    safety_flags: list[SafetyFlag]
    confirmed_facts: Annotated[list[StatedFact], Field(max_length=10)]
    open_questions: Annotated[list[Annotated[str, Field(max_length=200)]], Field(max_length=5)]
    missing_claims: Annotated[list[Annotated[str, Field(pattern=r"^[a-z_]{2,40}$")]], Field(max_length=10)]
    recommended_action: Action
    escalate: bool
    citations: Annotated[list[Citation], Field(max_length=20)]
    snapshot: Snapshot
    abstention_codes: list[Abstention]
    composer_version: str
    policy_version: str
    model_version: None
    prompt_version: None
    tool_calls: Literal[0]
    generated_at: datetime

    @classmethod
    def validated(cls, payload: dict[str, object], message_text: str, claim_digests: set[str]) -> "ReplyProposal":
        """Schema, abstention consistency, facts anchored to the message, and citations from the snapshot only."""
        try:
            proposal = cls.model_validate(payload)
        except ValidationError as exc:
            raise InvalidProposal(f"reply.v1 rejected: {exc.error_count()} error(s)") from None
        if (proposal.status == "proposed") != (proposal.proposed_reply is not None):
            raise InvalidProposal("a proposal has text exactly when it is proposed")
        if proposal.status == "abstained" and not proposal.abstention_codes:
            raise InvalidProposal("an abstention must say why")
        if proposal.status == "proposed" and proposal.abstention_codes:
            raise InvalidProposal("a proposed draft cannot carry abstention codes")
        for fact in proposal.confirmed_facts:
            if fact.end > len(message_text) or message_text[fact.start : fact.end] != fact.text:
                raise InvalidProposal("a stated fact is not quoted from the message")
        for citation in proposal.citations:
            if citation.digest not in claim_digests:
                raise InvalidProposal("a citation is not in the knowledge snapshot")
        return proposal
