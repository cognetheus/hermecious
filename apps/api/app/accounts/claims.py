"""Allowlisted fact claim types with typed values (Batch 02 §P1.2.2).

Absence is never a negative claim: no claim type can say "no website" or
"no software". Unknown is represented explicitly and can only be a
hypothesis with `unknown` confidence, never a source-supported finding.
Contact details are not facts (contacts and consent are a separate model).
"""

from datetime import date
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, field_validator

from app.accounts.policy import PolicyViolation

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]


class _Claim(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    @property
    def is_unknown(self) -> bool:
        return False


class CampusCount(_Claim):
    count: int = Field(ge=1, le=500)


class SchoolLevels(_Claim):
    levels: list[Literal["preschool", "primary", "middle", "secondary", "higher_secondary", "o_a_levels"]] = Field(
        min_length=1, max_length=6
    )


class OwnershipType(_Claim):
    type: Literal["independent", "franchise", "chain_campus", "trust", "unknown"]

    @property
    def is_unknown(self) -> bool:
        return self.type == "unknown"


class DecisionAuthority(_Claim):
    holder: Literal["owner", "principal", "board", "head_office", "unknown"]

    @property
    def is_unknown(self) -> bool:
        return self.holder == "unknown"


class PublicWorkflowSignal(_Claim):
    area: Literal["admissions", "fees", "student_records", "reporting", "communication"]
    signal: ShortText


class SoftwareInUse(_Claim):
    # "observed" names a product seen in a source; there is deliberately no "none".
    status: Literal["observed", "unknown"]
    product: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)] | None = None

    @property
    def is_unknown(self) -> bool:
        return self.status == "unknown"

    def model_post_init(self, context: Any, /) -> None:
        if (self.status == "observed") != (self.product is not None):
            raise ValueError("product is required exactly when status is observed")


class WebsitePresence(_Claim):
    status: Literal["present", "unknown"]

    @property
    def is_unknown(self) -> bool:
        return self.status == "unknown"


class PublicContactChannel(_Claim):
    # Which kind of channel is publicly listed, never the address itself.
    channel: Literal["website_form", "public_phone_listed", "public_email_listed", "social_page"]


class HardDisqualifier(_Claim):
    """P3.3: a documented reason the school must not be pursued (respected as `exclude`)."""

    reason: Literal["school_closed", "not_a_school", "outside_service_area", "declined_vendor_contact"]


class ReviewDeferral(_Claim):
    """P3.3: a documented request or reason to revisit later (drives `nurture`; creates no reminder)."""

    reason: Literal["asked_to_reconnect_later", "contract_in_place", "budget_cycle", "term_in_progress"]
    until: Annotated[str, StringConstraints(pattern=r"^\d{4}-\d{2}-\d{2}$")]

    @field_validator("until")
    @classmethod
    def _real_date(cls, value: str) -> str:
        date.fromisoformat(value)  # rejects impossible dates such as 2026-02-30
        return value


CLAIMS: dict[str, type[_Claim]] = {
    "campus_count": CampusCount,
    "school_levels": SchoolLevels,
    "ownership_type": OwnershipType,
    "decision_authority": DecisionAuthority,
    "public_workflow_signal": PublicWorkflowSignal,
    "software_in_use": SoftwareInUse,
    "website_presence": WebsitePresence,
    "public_contact_channel": PublicContactChannel,
    "hard_disqualifier": HardDisqualifier,
    "review_deferral": ReviewDeferral,
}


def parse_claim(claim_type: str, value: Any) -> _Claim:
    model = CLAIMS.get(claim_type)
    if model is None:
        raise PolicyViolation("claim type is not on the allowlist")
    if not isinstance(value, dict):
        raise PolicyViolation("claim value must be an object")
    try:
        return model.model_validate(value)
    except (ValidationError, ValueError):
        raise PolicyViolation("claim value is invalid for its type") from None
