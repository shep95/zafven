"""Lenient birth-date parsing shared across cogs."""
from __future__ import annotations

from datetime import datetime, date

_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y")


def parse_date(value: str) -> date:
    value = value.strip()
    for fmt in _FORMATS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise ValueError("Use a date like 1995-08-23 (YYYY-MM-DD).")
