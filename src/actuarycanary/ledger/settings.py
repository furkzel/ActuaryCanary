"""Run settings of the ledger reconciliation (CV12, record 0603): the materiality of a gap."""

from pydantic import BaseModel, ConfigDict, Field


class LedgerSettings(BaseModel):
    """A gap is material when its absolute value exceeds both `materiality_amount` and
    `materiality_ratio` times the absolute ledger amount (CV12)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    materiality_ratio: float = Field(default=0.005, ge=0)
    materiality_amount: float = Field(default=0.0, ge=0)
