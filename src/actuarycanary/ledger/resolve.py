"""The profile a run uses (CV12): the saved one for this chart of accounts, or a proposal that is
saved with `confirmed_on` empty and used at once, labelled as not confirmed (record 0421)."""

from pathlib import Path

import polars as pl

from actuarycanary.ledger.profile import (
    ProfileInUse,
    chart_fingerprint,
    profile_path,
    profile_sha256,
    read_profile,
    save_profile,
)
from actuarycanary.ledger.proposal import propose_profile


def profile_in_use(
    ledger: pl.DataFrame, folder: Path | None, fiscal_year_start_month: int = 1
) -> ProfileInUse:
    """The saved profile of the chart of accounts in `ledger` (raises `ProfileError` when the
    file cannot be read), or a new proposal, saved in `folder` when there is one."""
    key = chart_fingerprint(ledger["account"].unique().to_list())
    if folder is not None and (path := profile_path(folder, key)).is_file():
        profile, sha = read_profile(path)
        return ProfileInUse(profile, sha, path, saved=True)
    profile = propose_profile(ledger, fiscal_year_start_month)
    path = save_profile(folder, profile) if folder is not None else None
    return ProfileInUse(profile, profile_sha256(profile), path, saved=False)
