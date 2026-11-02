"""The `intent.v1` contract (P6.1, ADR-031). Validated on the server before anything is stored.

Exactly ten primary intents, eight safety flags and ten read-only recommended actions. Anything else, including an
invented action, a probability, or an evidence span that does not quote the message exactly, is rejected.
"""

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

PrimaryIntent = Literal[
    "interested", "needs_details", "objection", "request_demo", "defer", "not_interested", "opt_out",
    "human_request", "ambiguous", "abusive",
]  # fmt: skip
SafetyFlag = Literal[
    "explicit_opt_out", "human_escalation_requested", "possible_sensitive_personal_data", "abusive_or_threatening",
    "injection_attempt_suspected", "model_uncertain", "unsupported_language", "service_window_unknown",
]  # fmt: skip
Action = Literal[
    "review_interest", "review_details_request", "review_objection", "review_demo_request", "review_defer",
    "review_disinterest", "request_opt_out_review", "route_to_human", "review_abuse", "manual_triage",
]  # fmt: skip
Language = Literal["english", "roman_urdu", "urdu_script", "mixed", "unknown"]
Confidence = Literal["high", "medium", "low", "unknown"]

INTENTS: tuple[str, ...] = PrimaryIntent.__args__  # type: ignore[attr-defined]
# Primary-label precedence when several intents are present (docs/intent/annotation-guidelines.md).
PRECEDENCE = ("opt_out", "abusive", "request_demo", "needs_details", "human_request", "objection", "defer",
              "not_interested", "interested")  # fmt: skip
ACTION_FOR: dict[str, str] = {
    "interested": "review_interest", "needs_details": "review_details_request", "objection": "review_objection",
    "request_demo": "review_demo_request", "defer": "review_defer", "not_interested": "review_disinterest",
    "opt_out": "request_opt_out_review", "human_request": "route_to_human", "abusive": "review_abuse",
    "ambiguous": "manual_triage",
}  # fmt: skip


class InvalidObservation(ValueError):
    pass


class Span(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    start: Annotated[int, Field(ge=0)]
    end: Annotated[int, Field(ge=1)]
    text: Annotated[str, Field(max_length=500)]
    reason: Annotated[str, Field(pattern=r"^[a-z_]+:\d{1,3}$")]


class IntentObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["intent.v1"]
    message_id: Annotated[str, Field(min_length=1, max_length=64)]
    primary_intent: PrimaryIntent
    secondary_intents: Annotated[list[PrimaryIntent], Field(max_length=9)]
    safety_flags: Annotated[list[SafetyFlag], Field(max_length=8)]
    language: Language
    evidence: Annotated[list[Span], Field(max_length=40)]
    confidence: Confidence
    requires_human_review: bool
    recommended_action: Action
    reason_codes: Annotated[list[Annotated[str, Field(pattern=r"^[a-z_]{3,60}$")]], Field(max_length=10)]
    classifier_version: Annotated[str, Field(pattern=r"^[a-z0-9.-]{3,40}$")]
    rules_version: Annotated[str, Field(pattern=r"^[a-z0-9.-]{3,40}$")]
    model_version: str | None
    prompt_version: str | None
    classified_at: datetime

    @field_validator("secondary_intents", "safety_flags")
    @classmethod
    def _unique(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("duplicates")
        return value

    @classmethod
    def validated(cls, payload: dict[str, Any], text: str) -> "IntentObservation":
        """Schema, the action allowlist for the primary label, and evidence anchored to the exact message."""
        try:
            observation = cls.model_validate(payload)
        except ValidationError as exc:
            raise InvalidObservation(f"intent.v1 rejected: {exc.error_count()} error(s)") from None
        if observation.recommended_action != ACTION_FOR[observation.primary_intent]:
            raise InvalidObservation("recommended_action does not match the primary intent")
        if observation.primary_intent in observation.secondary_intents:
            raise InvalidObservation("the primary intent is repeated as secondary")
        if observation.primary_intent == "opt_out" and "explicit_opt_out" not in observation.safety_flags:
            raise InvalidObservation("an opt-out must carry the explicit_opt_out flag")
        for span in observation.evidence:
            if span.end > len(text) or span.start >= span.end or text[span.start : span.end] != span.text:
                raise InvalidObservation("evidence is not anchored to the message")
        return observation
