"""Active plan pruning — must match static/index.html readActivePlans logic."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from active_plan_prune import active_plan_should_prune, seattle_yyyymmdd_from_ms

_SEATTLE = ZoneInfo("America/Los_Angeles")


def test_prune_when_min_leg_before_today():
    # Link 5/11 + bus 5/12 → min 11 < 12 → drop on 5/12
    assert active_plan_should_prune([20260512, 20260511, 20260512], None, 20260512) is True


def test_keep_when_all_legs_same_service_day_as_today():
    ms_noon_may12 = int(datetime(2026, 5, 12, 12, 0, 0, tzinfo=_SEATTLE).timestamp() * 1000)
    assert active_plan_should_prune([20260512, 20260512], ms_noon_may12, 20260512) is False


def test_prune_when_oba_service_dates_all_today_but_followed_yesterday():
    """OBA can stamp every leg as the next service day; still drop after follow calendar day."""
    ms_may_11_afternoon = int(datetime(2026, 5, 11, 12, 28, 21, tzinfo=_SEATTLE).timestamp() * 1000)
    assert active_plan_should_prune([20260512, 20260512, 20260512], ms_may_11_afternoon, 20260512) is True


def test_prune_when_only_max_before_today_and_no_min_ambiguity():
    """All legs share same past service date."""
    assert active_plan_should_prune([20260510], None, 20260512) is True


def test_fallback_added_date_when_no_service_dates():
    # Added Seattle 5/11, today 5/12, no leg dates → prune
    ms_may_11 = int(datetime(2026, 5, 11, 22, 0, 0, tzinfo=_SEATTLE).timestamp() * 1000)
    assert seattle_yyyymmdd_from_ms(ms_may_11) == 20260511
    assert active_plan_should_prune([], ms_may_11, 20260512) is True


def test_keep_when_no_leg_dates_but_added_today():
    ms_may_12 = int(datetime(2026, 5, 12, 1, 0, 0, tzinfo=_SEATTLE).timestamp() * 1000)
    assert active_plan_should_prune([], ms_may_12, 20260512) is False


@pytest.mark.parametrize(
    "raw,expect",
    [
        (["20260511", 20260512], True),
        ([None, 20260512, ""], False),
        ([20260513], False),
    ],
)
def test_prune_param_edge_strings(raw, expect):
    today = 20260512
    assert active_plan_should_prune(raw, None, today) is expect
