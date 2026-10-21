"""Constant development rates for triangles and the methods built on them (CV01)."""


def development_rates(reporting_currency: str) -> dict[str, float]:
    """Rate per original currency into the reporting currency at the development rate date.

    Market data is not read yet, so only amounts already in the reporting currency have a
    rate (1). Every other currency stays unconverted and is reported separately (CV01).
    """
    return {reporting_currency: 1.0}
