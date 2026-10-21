"""Reserving module (M04), first slice: chain ladder on paid and incurred triangles per group."""

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from actuarycanary.methods.chain_ladder import Average, ChainLadder, Skipped, chain_ladder
from actuarycanary.structures.triangles import MEASURES, Triangle, TriangleSet


class ChainLadderSettings(BaseModel):
    """MT02 parameters; exclusions and factor overrides come with the assumptions register."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    average: Average = Average.VOLUME_WEIGHTED
    n_diagonals: int | None = Field(default=None, ge=1)
    exclude_high_low: bool = False
    tail_factor: float = Field(default=1.0, gt=0)
    min_origins: int = Field(default=3, ge=2)


@dataclass(frozen=True)
class OriginEstimate:
    """RS02 per origin and method: ultimate, unpaid (U - paid) and IBNR (U - incurred)."""

    origin: str
    paid: float
    incurred: float
    ultimate: dict[str, float | None]  # per method: "paid", "incurred"

    def unpaid(self, method: str) -> float | None:
        ultimate = self.ultimate[method]
        return None if ultimate is None else ultimate - self.paid

    def ibnr(self, method: str) -> float | None:
        ultimate = self.ultimate[method]
        return None if ultimate is None else ultimate - self.incurred


@dataclass(frozen=True)
class GroupReserving:
    group: tuple[str, ...]
    triangles: dict[str, Triangle]  # by measure
    chain_ladder: dict[str, ChainLadder | Skipped]  # by measure of the triangle it ran on

    def estimates(self) -> list[OriginEstimate]:
        paid, incurred = self.triangles["paid"].latest, self.triangles["incurred"].latest
        rows: list[OriginEstimate] = []
        for i, origin in enumerate(self.triangles["paid"].origins):
            ultimate: dict[str, float | None] = {}
            for measure, result in self.chain_ladder.items():
                ultimate[measure] = (
                    float(result.ultimate[i]) if isinstance(result, ChainLadder) else None
                )
            rows.append(OriginEstimate(origin, float(paid[i]), float(incurred[i]), ultimate))
        return rows

    def totals(self) -> OriginEstimate:
        rows = self.estimates()
        ultimate: dict[str, float | None] = {}
        for measure in self.chain_ladder:
            known = [v for r in rows if (v := r.ultimate[measure]) is not None]
            ultimate[measure] = float(sum(known)) if len(known) == len(rows) else None
        return OriginEstimate(
            "Total",
            float(sum(r.paid for r in rows)),
            float(sum(r.incurred for r in rows)),
            ultimate,
        )


@dataclass(frozen=True)
class ReservingResult:
    triangles: TriangleSet
    settings: ChainLadderSettings
    groups: tuple[GroupReserving, ...]


def run_reserving(triangles: TriangleSet, settings: ChainLadderSettings) -> ReservingResult:
    groups: list[GroupReserving] = []
    for group in triangles.groups:
        by_measure = {m: triangles.get(m, group) for m in MEASURES}
        results = {
            m: chain_ladder(
                t.cumulative,
                average=settings.average,
                n_diagonals=settings.n_diagonals,
                exclude_high_low=settings.exclude_high_low,
                tail_factor=settings.tail_factor,
                min_origins=settings.min_origins,
                calendar=t.calendar,
            )
            for m, t in by_measure.items()
        }
        groups.append(GroupReserving(group, by_measure, results))
    return ReservingResult(triangles, settings, tuple(groups))
