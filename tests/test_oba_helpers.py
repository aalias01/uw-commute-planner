"""Unit tests for OBA matching and timing helpers (no network)."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from app import (
    SEATTLE,
    MAX_REALISTIC_DELAY_NOTE_MINUTES,
    TrackLegSpec,
    TrackRefreshBody,
    depart_time,
    find_arrival_row,
    live_vs_schedule_arrival_note,
    live_vs_schedule_depart_note,
    platform_arrival_time,
)


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def test_find_arrival_row_empty():
    assert find_arrival_row([], "t1", 20260512, "40_100479") is None


def test_find_arrival_row_match_route():
    arrivals = [
        {
            "tripId": "t1",
            "serviceDate": 20260512,
            "routeId": "40_100479",
            "predictedDepartureTime": 0,
            "scheduledDepartureTime": _ms(datetime(2026, 5, 12, 20, 0, tzinfo=SEATTLE)),
        }
    ]
    row = find_arrival_row(arrivals, "t1", 20260512, "40_100479")
    assert row is not None
    assert row["routeId"] == "40_100479"


def test_find_arrival_row_service_date_string():
    arrivals = [
        {
            "tripId": "t1",
            "serviceDate": "20260512",
            "routeId": "40_100479",
            "scheduledDepartureTime": _ms(datetime(2026, 5, 12, 20, 0, tzinfo=SEATTLE)),
        }
    ]
    row = find_arrival_row(arrivals, "t1", 20260512, "40_100479")
    assert row is not None


def test_find_arrival_row_fallback_when_route_mismatch():
    """Prefer route_id, but still match trip + serviceDate if OBA uses another route id."""
    arrivals = [
        {
            "tripId": "t1",
            "serviceDate": 20260512,
            "routeId": "40_2LINE",
            "scheduledDepartureTime": _ms(datetime(2026, 5, 12, 20, 0, tzinfo=SEATTLE)),
        }
    ]
    row = find_arrival_row(arrivals, "t1", 20260512, "40_100479")
    assert row is not None
    assert row["routeId"] == "40_2LINE"


def test_find_arrival_row_multiple_same_trip_prefers_route():
    a1 = {
        "tripId": "t1",
        "serviceDate": 20260512,
        "routeId": "40_2LINE",
        "scheduledDepartureTime": _ms(datetime(2026, 5, 12, 19, 0, tzinfo=SEATTLE)),
    }
    a2 = {
        "tripId": "t1",
        "serviceDate": 20260512,
        "routeId": "40_100479",
        "scheduledDepartureTime": _ms(datetime(2026, 5, 12, 20, 0, tzinfo=SEATTLE)),
    }
    row = find_arrival_row([a1, a2], "t1", 20260512, "40_100479")
    assert row["routeId"] == "40_100479"


def test_depart_time_predicted_over_scheduled():
    t_pred = _ms(datetime(2026, 5, 12, 20, 5, tzinfo=SEATTLE))
    t_sched = _ms(datetime(2026, 5, 12, 20, 0, tzinfo=SEATTLE))
    row = {
        "predictedDepartureTime": t_pred,
        "scheduledDepartureTime": t_sched,
    }
    assert depart_time(row) == datetime.fromtimestamp(t_pred / 1000, tz=SEATTLE)


def test_depart_time_falls_back_to_arrival_when_no_departure():
    ta = _ms(datetime(2026, 5, 12, 20, 7, tzinfo=SEATTLE))
    row = {
        "predictedDepartureTime": 0,
        "scheduledDepartureTime": 0,
        "predictedArrivalTime": ta,
        "scheduledArrivalTime": 0,
    }
    assert depart_time(row) == datetime.fromtimestamp(ta / 1000, tz=SEATTLE)


def test_depart_time_all_zero_uses_now_and_seattle_tz():
    row = {
        "tripId": "ghost",
        "serviceDate": 20260512,
        "routeId": "40_100479",
        "predictedDepartureTime": 0,
        "scheduledDepartureTime": 0,
        "predictedArrivalTime": 0,
        "scheduledArrivalTime": 0,
    }
    fixed = datetime(2026, 5, 12, 15, 30, tzinfo=SEATTLE)
    with patch("app.datetime") as mock_dt:
        mock_dt.now.return_value = fixed
        mock_dt.fromtimestamp = datetime.fromtimestamp
        assert depart_time(row) == fixed


def test_platform_arrival_time_falls_back_to_departure():
    td = _ms(datetime(2026, 5, 12, 20, 1, tzinfo=SEATTLE))
    row = {
        "predictedArrivalTime": 0,
        "scheduledArrivalTime": 0,
        "predictedDepartureTime": td,
        "scheduledDepartureTime": 0,
    }
    assert platform_arrival_time(row) == datetime.fromtimestamp(td / 1000, tz=SEATTLE)


def test_live_vs_schedule_depart_note_suppressed_when_huge_delta():
    base = _ms(datetime(2026, 5, 12, 12, 0, tzinfo=SEATTLE))
    delta_ms = (MAX_REALISTIC_DELAY_NOTE_MINUTES + 10) * 60_000
    row = {
        "predicted": True,
        "predictedDepartureTime": base + delta_ms,
        "scheduledDepartureTime": base,
    }
    assert live_vs_schedule_depart_note(row) is None


def test_live_vs_schedule_depart_note_small_delay():
    base = _ms(datetime(2026, 5, 12, 12, 0, tzinfo=SEATTLE))
    row = {
        "predicted": True,
        "predictedDepartureTime": base + 3 * 60_000,
        "scheduledDepartureTime": base,
    }
    assert live_vs_schedule_depart_note(row) == "3 min delay"


def test_live_vs_schedule_arrival_note_small_early():
    base = _ms(datetime(2026, 5, 12, 12, 0, tzinfo=SEATTLE))
    row = {
        "predicted": True,
        "predictedArrivalTime": base - 2 * 60_000,
        "scheduledArrivalTime": base,
    }
    assert live_vs_schedule_arrival_note(row) == "2 min early"


def test_track_refresh_body_max_legs():
    legs = [
        TrackLegSpec(
            role="link_udist",
            label="L",
            stop_id="s",
            trip_id="t",
            service_date=20260512,
            route_id=None,
        )
    ] * 33
    with pytest.raises(ValidationError):
        TrackRefreshBody(legs=legs)


def test_track_refresh_body_accepts_max_legs():
    legs = [
        TrackLegSpec(
            role="link_udist",
            label="L",
            stop_id="s",
            trip_id="t",
            service_date=20260512,
            route_id=None,
        )
    ] * 32
    body = TrackRefreshBody(legs=legs)
    assert len(body.legs) == 32
