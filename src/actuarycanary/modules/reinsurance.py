"""M08 Reinsurance: what is ceded and what is net, treaty by treaty, the reconciliation with
the ceded amounts the data report, and what another programme would cede (MT21, CV09)."""

from pydantic import BaseModel, ConfigDict, field_validator

from actuarycanary.convert.allocation import AGGREGATE, FALLBACKS
from actuarycanary.methods.reinsurance.index import INDEX_CLAUSES, PAYMENT_BY_PAYMENT

LOSS_VIEWS = ("incurred", "ultimate")
PROGRAMMES = ("loaded", "alternative", "both")


class ReinsuranceSettings(BaseModel):
    """Settings of M08 and MT21 (records 0401, 0403 and 0408); part of the run id."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    # how an index clause works: payment by payment (the owner's choice, record 0401) or
    # fixed at the occurrence date (the generator's clause)
    index_clause: str = PAYMENT_BY_PAYMENT
    # CV09: what happens to a treaty-level amount that cannot be allocated to claims or policies
    allocation_fallback: str = AGGREGATE
    # MT21: the loaded treaties, an alternative from the assumptions register, or both
    programme: str = "loaded"
    loss_view: str = "ultimate"
    # MT21 `simulate` is not built (record 0408): only false is accepted
    simulate: bool = False
    inuring_order: str = "CV09"

    @field_validator("index_clause")
    @classmethod
    def _known_clause(cls, value: str) -> str:
        if value not in INDEX_CLAUSES:
            raise ValueError(
                f"index clause {value!r} is unknown; known: {', '.join(INDEX_CLAUSES)}"
            )
        return value

    @field_validator("allocation_fallback")
    @classmethod
    def _known_fallback(cls, value: str) -> str:
        if value not in FALLBACKS:
            raise ValueError(
                f"allocation fallback {value!r} is unknown; known: {', '.join(FALLBACKS)}"
            )
        return value

    @field_validator("programme")
    @classmethod
    def _known_programme(cls, value: str) -> str:
        if value not in PROGRAMMES:
            raise ValueError(f"programme {value!r} is unknown; known: {', '.join(PROGRAMMES)}")
        return value

    @field_validator("loss_view")
    @classmethod
    def _known_view(cls, value: str) -> str:
        if value not in LOSS_VIEWS:
            raise ValueError(f"loss view {value!r} is unknown; known: incurred and ultimate")
        return value

    @field_validator("simulate")
    @classmethod
    def _not_built(cls, value: bool) -> bool:
        if value:
            raise ValueError("simulate is not built (MT21, record 0408): only false is accepted")
        return value

    @field_validator("inuring_order")
    @classmethod
    def _cv09_only(cls, value: str) -> str:
        if value != "CV09":
            raise ValueError("inuring order: only CV09 is built (record 0604)")
        return value
