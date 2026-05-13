"""
Active-tab card pruning vs Seattle local calendar.

Must stay in sync with ``static/index.html``:
``legServiceDate`` / ``activePlanMinServiceDate`` / ``activePlanMaxServiceDate`` /
``getSeattleDateIntFromMs`` / ``isActivePlanPastServiceDay`` / ``readActivePlans``.

Prune when the earliest leg ``service_date`` is before Seattle today, **or** when
``addedAt`` (Seattle calendar) is before today — so trips followed yesterday drop
even if every leg still carries today's OBA ``service_date``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from zoneinfo import ZoneInfo

_SEATTLE = ZoneInfo("America/Los_Angeles")


def seattle_yyyymmdd_from_ms(ms: float | int) -> int:
    """Calendar YYYYMMDD in America/Los_Angeles for an epoch-ms timestamp."""
    return int(datetime.fromtimestamp(float(ms) / 1000, tz=_SEATTLE).strftime("%Y%m%d"))


def active_plan_should_prune(
    leg_service_dates: list[Optional[Any]],
    added_at_ms: Optional[float | int],
    today_yyyymmdd: int,
) -> bool:
    """
    Return True if a followed plan should be removed when the Active list loads.

    ``leg_service_dates``: ``service_date`` from each tracking leg (ints or numeric strings).
    ``added_at_ms``: plan ``addedAt`` from localStorage (epoch ms). Compared in Seattle
    local calendar to ``today_yyyymmdd``; if the follow day is before today, the plan
    is pruned even when every leg ``service_date`` equals today (OBA midnight boundary).
    ``today_yyyymmdd``: Seattle ``YYYYMMDD`` for "now" (inject in tests).
    """
    values: list[int] = []
    for sd in leg_service_dates:
        if sd is None or sd == "":
            continue
        if isinstance(sd, bool):
            continue
        try:
            n = int(sd)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        values.append(n)

    min_sd = min(values) if values else None
    max_sd = max(values) if values else None

    if min_sd is not None and min_sd < today_yyyymmdd:
        return True
    if min_sd is None and max_sd is not None and max_sd < today_yyyymmdd:
        return True
    if added_at_ms is not None:
        add_d = seattle_yyyymmdd_from_ms(added_at_ms)
        if add_d < today_yyyymmdd:
            return True
    return False
