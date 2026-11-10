"""The settings form of the interface: the options of `canary run`, with the same defaults.

`build_run_settings` builds the `RunSettings` exactly as `run_command` of the command line does
(a test compares the two), and `command_line` writes the command the choices correspond to.
"""

import shlex
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from actuarycanary.convert.bases import ReinsuranceBasis, ValueBasis
from actuarycanary.convert.discount import DiscountSettings
from actuarycanary.measures.lineage import DEFAULT_FORMAT, FORMATS
from actuarycanary.methods.assumptions import AssumptionsRegister
from actuarycanary.pipeline import RunSettings
from actuarycanary.report.language import LANGUAGES
from actuarycanary.structures.periods import Period
from actuarycanary.structures.triangles import OriginAxis, TriangleSettings

DEFAULT_OUT = "out"
DEFAULT_PROFILES = "profiles"

BASES = tuple(b.value.lower() for b in ReinsuranceBasis)
VALUES = tuple(v.value.lower().replace("_", "-") for v in ValueBasis)
ORIGIN_AXES = tuple(a.value for a in OriginAxis)
PERIODS = tuple(p.value.lower() for p in Period)
CURRENCY_VIEWS = ("reporting", "original")

# option name of `canary run`, key of the form, default; a value equal to the default is left out
# of the command line
_OPTIONS: tuple[tuple[str, str, str], ...] = (
    ("--origin-period", "origin_period", "year"),
    ("--development-period", "development_period", "year"),
    ("--origin-axis", "origin_axis", "accident"),
    ("--basis", "basis", "gross"),
    ("--currency", "currency", ""),
    ("--value", "value", "nominal"),
    ("--value-date", "value_date", ""),
    ("--price-index", "price_index", ""),
    ("--curve", "curve", ""),
    ("--discount-date", "discount_date", ""),
    ("--currency-view", "currency_view", "reporting"),
    ("--lang", "lang", "en"),
    ("--lineage-format", "lineage_format", str(DEFAULT_FORMAT)),
    ("--assumptions", "assumptions", ""),
)


class SettingsRejectedError(ValueError):
    """The choices do not make settings; the message is the one of the command line."""


@dataclass(frozen=True)
class Form:
    """The choices of the start page, every one a text as typed (empty: the default)."""

    folder: str = ""
    out: str = ""  # empty: the output folder the program was started with
    profiles: str = ""  # empty: the profiles folder the program was started with
    values: Mapping[str, str] | None = None

    def get(self, key: str, default: str = "") -> str:
        text = (self.values or {}).get(key)
        return default if text is None or not str(text).strip() else str(text).strip()


def form_from_json(data: Mapping[str, Any]) -> Form:
    """A form from the JSON the page sends; every value becomes text."""
    text = {k: "" if v is None else str(v) for k, v in data.items()}
    return Form(
        folder=text.get("folder", "").strip(),
        out=text.get("out", "").strip(),
        profiles=text.get("profiles", "").strip(),
        values=text,
    )


def _choice(form: Form, key: str, allowed: tuple[str, ...], default: str, name: str) -> str:
    text = form.get(key, default).lower()
    if text not in allowed:
        raise SettingsRejectedError(f"{name} {text!r} is unknown; known: {', '.join(allowed)}")
    return text


def build_run_settings(form: Form) -> RunSettings:
    """The `RunSettings` of the form, built as `canary run` builds them."""
    language = _choice(form, "lang", LANGUAGES, "en", "language")
    basis = _choice(form, "basis", BASES, "gross", "basis")
    value = _choice(form, "value", VALUES, "nominal", "value basis")
    view = _choice(form, "currency_view", CURRENCY_VIEWS, "reporting", "currency view")
    axis = _choice(form, "origin_axis", ORIGIN_AXES, "accident", "origin axis")
    origin = _choice(form, "origin_period", PERIODS, "year", "origin period")
    development = _choice(form, "development_period", PERIODS, "year", "development period")
    try:
        lineage = int(form.get("lineage_format", str(DEFAULT_FORMAT)))
    except ValueError as error:
        raise SettingsRejectedError("lineage format is a number: 1 or 2") from error
    if lineage not in FORMATS:
        raise SettingsRejectedError(f"lineage format {lineage} is unknown; known: 1 and 2")
    currency = form.get("currency")
    value_date = form.get("value_date")
    discount_date = form.get("discount_date")
    assumptions = form.get("assumptions")
    try:
        return RunSettings(
            reporting_currency=currency.upper() if currency else None,
            lineage_format=lineage,
            language=language,
            currency_view=view.upper(),
            triangles=TriangleSettings(
                origin_period=Period(origin.upper()),
                development_period=Period(development.upper()),
                origin_axis=OriginAxis(axis),
                reinsurance_basis=ReinsuranceBasis(basis.upper()),
                value_basis=ValueBasis(value.upper().replace("-", "_")),
                value_date=date.fromisoformat(value_date) if value_date else None,
                price_index=form.get("price_index") or None,
            ),
            assumptions=(
                AssumptionsRegister.from_yaml(Path(assumptions))
                if assumptions
                else AssumptionsRegister()
            ),
            discount=DiscountSettings(
                curve_id=form.get("curve") or None,
                discount_date=date.fromisoformat(discount_date) if discount_date else None,
            ),
        )
    except (ValueError, OSError) as error:
        raise SettingsRejectedError(str(error)) from error


def _quote(parts: list[str]) -> str:
    return subprocess.list2cmdline(parts) if sys.platform == "win32" else shlex.join(parts)


def command_line(form: Form, with_yes: bool) -> str:
    """The `canary run` command the choices correspond to.

    Options at their default are left out, and so are --out and --profiles when empty (`Form`
    holds only what differs from the defaults of the command line). `with_yes` adds --yes, which
    is what a run of the interface without a confirmed mapping is.
    """
    parts = ["canary", "run", form.folder or "<folder>"]
    if form.out:
        parts += ["--out", form.out]
    for option, key, default in _OPTIONS:
        text = form.get(key, default)
        if key in {"basis", "value", "origin_axis", "origin_period", "development_period"}:
            text = text.lower()
        if text != default:
            parts += [option, text.upper() if option == "--currency" else text]
    if form.profiles:
        parts += ["--profiles", form.profiles]
    if with_yes:
        parts.append("--yes")
    return _quote(parts)
