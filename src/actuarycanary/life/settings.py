"""The `life` settings of a run: the defaults of CV11 (record 0441). Part of the run settings,
so of the run id."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class LifeSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    # how the source's age_band counts age; the arithmetic is the same, the label differs
    age_definition: Literal["age_last_birthday", "age_nearest_birthday"] = "age_last_birthday"
    # the exposure measure of the studies (central is the default of CV11)
    exposure: Literal["central", "initial"] = "central"
    # how study time is cut besides age and policy year
    study_cells: Literal["calendar_year", "policy_year"] = "calendar_year"
    # width in years of the age bands of the outputs; finer source ages are grouped
    age_band_width: int = Field(default=5, ge=1, le=20)
    # months before the cut-off left out of mortality cells (deaths are reported late)
    reporting_lag_months: int = Field(default=3, ge=0, le=24)
    # sex is dropped on load unless this is true, and then used only in aggregated cells
    use_sex: bool = False
