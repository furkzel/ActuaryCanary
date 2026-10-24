"""Ceded claim amounts: surplus, quota shares, per-claim and per-event excess of loss.

Treaties apply in this order: surplus first, then quota shares on what is left, then excess of
loss on what the insurer keeps. Retentions and limits are fixed per claim at the occurrence date's
price level (a stabilisation clause), or per event at the event date's. A surplus treaty cedes a
share of every claim of a policy that is fixed by the policy's sum insured at its start.
"""

import numpy as np

from actuarycanary.synthetic.claims import ClaimWorld
from actuarycanary.synthetic.days import to_day
from actuarycanary.synthetic.market import Market
from actuarycanary.synthetic.portfolio import Policies
from actuarycanary.synthetic.scenario import Scenario, SurplusTreaty, Treaty


def surplus_policy_share(policies: Policies, market: Market, surplus: SurplusTreaty) -> np.ndarray:
    """Share of each policy that the surplus treaty takes: the part of the sum insured above the
    retained line, up to the capacity of the treaty, as a share of the sum insured. Sums insured
    in a foreign currency are converted at the rate of the policy start."""
    start = policies.start
    scale = market.price_factor(start) if surplus.retention_indexed_to else 1.0
    line = surplus.retained_line * scale
    insured = policies.sum_insured * policies.units
    for code in market.fx:
        foreign = policies.currency == code
        if foreign.any():
            insured = np.where(foreign, insured * market.fx_at(code, start), insured)
    capacity = surplus.number_of_lines * line
    return np.where(
        insured > 0,
        np.clip(insured - line, 0.0, capacity) / np.where(insured > 0, insured, 1.0),
        0.0,
    )


class Reinsurance:
    def __init__(self, scenario: Scenario, world: ClaimWorld) -> None:
        self.world = world
        n = len(world)
        occ = world.c_occ
        self.quota = np.zeros(n)
        self.claim_treaties: list[
            tuple[np.ndarray, np.ndarray, np.ndarray]
        ] = []  # mask, retention, limit
        self.event_treaties: list[tuple[Treaty, np.ndarray]] = []
        self.claim_treaty_ids: list[str] = []
        self.covered_by: dict[str, np.ndarray] = {}  # treaty id -> claims in scope
        self.quota_parts: list[tuple[str, np.ndarray]] = []  # treaty id, ceded share of a claim
        self.surplus_parts: list[tuple[str, np.ndarray]] = []
        for treaty in scenario.reinsurance:
            covered = np.isin(world.c_line, treaty.lines) & (occ >= to_day(treaty.inception))
            if treaty.type == "QUOTA_SHARE":
                assert treaty.cession is not None
                self.quota[covered] += treaty.cession
                self.quota_parts.append((treaty.treaty_id, np.where(covered, treaty.cession, 0.0)))
                self.covered_by[treaty.treaty_id] = covered
        for surplus in scenario.phase2.surplus:
            covered = np.isin(world.c_line, surplus.lines) & (occ >= to_day(surplus.inception))
            share = np.where(covered, self._surplus_share(world, surplus), 0.0)
            self.surplus_parts.append((surplus.treaty_id, share))
            self.covered_by[surplus.treaty_id] = covered & (share > 0)
        for treaty in scenario.reinsurance:
            if treaty.type != "EXCESS_OF_LOSS":
                continue
            covered = np.isin(world.c_line, treaty.lines) & (occ >= to_day(treaty.inception))
            if treaty.basis == "event":
                self.event_treaties.append((treaty, covered & (world.c_event >= 0)))
                self.covered_by[treaty.treaty_id] = covered & (world.c_event >= 0)
                continue
            assert treaty.retention is not None and treaty.limit is not None
            scale = world.market.price_factor(occ) if treaty.retention_indexed_to else np.ones(n)
            foreign = world.c_fx_start != 1.0
            if (covered & foreign).any():
                raise ValueError(
                    f"{treaty.treaty_id}: a per-claim excess of loss cannot cover foreign claims"
                )
            self.claim_treaties.append((covered, treaty.retention * scale, treaty.limit * scale))
            self.claim_treaty_ids.append(treaty.treaty_id)
            self.covered_by[treaty.treaty_id] = covered
        self.retained = 1.0 - self.quota
        for _, share in self.surplus_parts:
            self.retained = self.retained * (1.0 - share)

    @staticmethod
    def _surplus_share(world: ClaimWorld, surplus: SurplusTreaty) -> np.ndarray:
        """Share of each claim that the surplus treaty takes (that of its policy)."""
        return surplus_policy_share(world.policies, world.market, surplus)[world.c_policy]

    def ceded(
        self, claim: np.ndarray, day: np.ndarray, paid: np.ndarray, reserve: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray]:
        """Ceded paid and ceded reserve of each claim at each day, given its gross state."""
        keep = self.retained[claim]
        ceded_paid = (1.0 - keep) * paid
        ceded_reserve = (1.0 - keep) * reserve
        net_paid, net_incurred = keep * paid, keep * (paid + reserve)
        for covered, retention, limit in self.claim_treaties:
            on = covered[claim]
            layer_paid = np.clip(net_paid - retention[claim], 0.0, limit[claim])
            layer_incurred = np.clip(net_incurred - retention[claim], 0.0, limit[claim])
            ceded_paid += np.where(on, layer_paid, 0.0)
            ceded_reserve += np.where(on, layer_incurred - layer_paid, 0.0)
        for treaty, covered in self.event_treaties:
            on = covered[claim]
            if not on.any():
                continue
            phi_paid, phi_incurred = self._event_fractions(treaty, covered, claim[on], day[on])
            layer_paid = phi_paid * net_paid[on]
            layer_reserve = np.clip(
                phi_incurred * net_incurred[on] - layer_paid, 0.0, keep[on] * reserve[on]
            )
            ceded_paid[on] += layer_paid
            ceded_reserve[on] += layer_reserve
        return ceded_paid, ceded_reserve

    def _event_fractions(
        self, treaty: Treaty, covered: np.ndarray, claim: np.ndarray, day: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray]:
        """Share of the retained event total that the layer pays, at each (claim, day)."""
        assert treaty.retention is not None and treaty.limit is not None
        world = self.world
        phi_paid = np.zeros(len(claim))
        phi_incurred = np.zeros(len(claim))
        events = world.c_event[claim]
        for event in np.unique(events):
            members = np.flatnonzero(covered & (world.c_event == event))
            at = np.flatnonzero(events == event)
            days = np.unique(day[at])
            grid_claim = np.repeat(members, len(days))
            grid_day = np.tile(days, len(members))
            state = world.state(grid_claim, grid_day)
            keep = self.retained[grid_claim]
            sums_paid = (keep * state["paid"]).reshape(len(members), len(days)).sum(axis=0)
            sums_incurred = (
                (keep * (state["paid"] + state["reserve"]))
                .reshape(len(members), len(days))
                .sum(axis=0)
            )
            scale = (
                float(world.market.price_factor(np.array([world.event_dates[int(event)]]))[0])
                if treaty.retention_indexed_to
                else 1.0
            )
            ret, lim = treaty.retention * scale, treaty.limit * scale
            ceded_paid = np.clip(sums_paid - ret, 0.0, lim)
            ceded_incurred = np.clip(sums_incurred - ret, 0.0, lim)
            share_paid = np.divide(
                ceded_paid, sums_paid, out=np.zeros_like(ceded_paid), where=sums_paid > 0
            )
            share_incurred = np.divide(
                ceded_incurred,
                sums_incurred,
                out=np.zeros_like(ceded_incurred),
                where=sums_incurred > 0,
            )
            position = np.searchsorted(days, day[at])
            phi_paid[at] = share_paid[position]
            phi_incurred[at] = share_incurred[position]
        return phi_paid, phi_incurred

    def ceded_parts(
        self, claim: np.ndarray, day: np.ndarray, paid: np.ndarray, reserve: np.ndarray
    ) -> list[tuple[str, np.ndarray, np.ndarray]]:
        """The ceded paid and ceded reserve of `ceded`, split by treaty.

        The parts add up to `ceded` (up to rounding in the last digits). Proportional treaties
        share what their combined cession takes in proportion to the share each one cedes;
        excess-of-loss layers are the same arithmetic as in `ceded`.
        """
        keep = self.retained[claim]
        gross_shares: list[tuple[str, np.ndarray]] = []
        left = np.ones(len(claim))
        for treaty_id, share in self.surplus_parts:
            taken = share[claim]
            gross_shares.append((treaty_id, taken * left))
            left = left * (1.0 - taken)
        for treaty_id, share in self.quota_parts:
            gross_shares.append((treaty_id, share[claim] * left))
        total_share = sum((w for _, w in gross_shares), np.zeros(len(claim)))
        prop_paid = (1.0 - keep) * paid
        prop_reserve = (1.0 - keep) * reserve
        parts: list[tuple[str, np.ndarray, np.ndarray]] = []
        for treaty_id, w in gross_shares:
            weight = np.divide(w, total_share, out=np.zeros(len(claim)), where=total_share > 0)
            parts.append((treaty_id, prop_paid * weight, prop_reserve * weight))
        net_paid, net_incurred = keep * paid, keep * (paid + reserve)
        for (covered, retention, limit), treaty_id in zip(
            self.claim_treaties, self.claim_treaty_ids, strict=True
        ):
            on = covered[claim]
            layer_paid = np.clip(net_paid - retention[claim], 0.0, limit[claim])
            layer_incurred = np.clip(net_incurred - retention[claim], 0.0, limit[claim])
            parts.append(
                (
                    treaty_id,
                    np.where(on, layer_paid, 0.0),
                    np.where(on, layer_incurred - layer_paid, 0.0),
                )
            )
        for treaty, covered in self.event_treaties:
            on = covered[claim]
            event_paid = np.zeros(len(claim))
            event_reserve = np.zeros(len(claim))
            if on.any():
                phi_paid, phi_incurred = self._event_fractions(treaty, covered, claim[on], day[on])
                layer_paid = phi_paid * net_paid[on]
                event_paid[on] = layer_paid
                event_reserve[on] = np.clip(
                    phi_incurred * net_incurred[on] - layer_paid, 0.0, keep[on] * reserve[on]
                )
            parts.append((treaty.treaty_id, event_paid, event_reserve))
        return parts
