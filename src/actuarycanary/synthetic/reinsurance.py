"""Ceded claim amounts: quota shares, per-claim excess of loss and per-event excess of loss.

Treaties apply in this order: quota shares first, then excess of loss on what the insurer
keeps. Retentions and limits are fixed per claim at the occurrence date's price level
(a stabilisation clause), or per event at the event date's.
"""

import numpy as np

from actuarycanary.synthetic.claims import ClaimWorld
from actuarycanary.synthetic.days import to_day
from actuarycanary.synthetic.scenario import Scenario, Treaty


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
        for treaty in scenario.reinsurance:
            covered = np.isin(world.c_line, treaty.lines) & (occ >= to_day(treaty.inception))
            if treaty.type == "QUOTA_SHARE":
                assert treaty.cession is not None
                self.quota[covered] += treaty.cession
        for treaty in scenario.reinsurance:
            if treaty.type != "EXCESS_OF_LOSS":
                continue
            covered = np.isin(world.c_line, treaty.lines) & (occ >= to_day(treaty.inception))
            if treaty.basis == "event":
                self.event_treaties.append((treaty, covered & (world.c_event >= 0)))
                continue
            assert treaty.retention is not None and treaty.limit is not None
            scale = world.market.price_factor(occ) if treaty.retention_indexed_to else np.ones(n)
            foreign = world.c_fx_start != 1.0
            if (covered & foreign).any():
                raise ValueError(
                    f"{treaty.treaty_id}: a per-claim excess of loss cannot cover foreign claims"
                )
            self.claim_treaties.append((covered, treaty.retention * scale, treaty.limit * scale))
        self.retained = 1.0 - self.quota

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
