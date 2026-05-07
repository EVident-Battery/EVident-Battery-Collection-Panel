"""Trial build expiration metadata.

Soft commercial gate for prebuilt binaries — anyone with the source can
build past it. See README for licensing.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

TRIAL_EXPIRY_DATE: date = date(2026, 7, 6)


def days_remaining(today: Optional[date] = None) -> int:
    """Days until expiry. Zero on the expiry date itself, negative once expired."""
    today = today or date.today()
    return (TRIAL_EXPIRY_DATE - today).days


def is_expired(today: Optional[date] = None) -> bool:
    return days_remaining(today) < 0
