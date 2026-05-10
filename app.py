from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import asyncio
import httpx
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

SEATTLE = ZoneInfo("America/Los_Angeles")
from typing import Optional

from pydantic import BaseModel, Field, field_validator
import uvicorn

# API key — set via environment variable before running:
#   export OBA_API_KEY=your_key_here
# Falls back to "TEST" (shared public key, may hit rate limits occasionally)
# To request your own key: email oba_api_key@soundtransit.org
API_KEY  = os.environ.get("OBA_API_KEY", "TEST")
OBA_BASE = "https://api.pugetsound.onebusaway.org/api/where"

# Stop IDs — verified via OBA (stops-for-route / arrivals samples)
STOPS = {
    "u_district_station":       "40_990002",   # U District, northbound Link platform (direction N)
    # Sound Transit Link northbound platform — alight here before walking to bus bays (not King County Metro bays).
    "shoreline_south_link_nb":  "40_N15-T1",   # Shoreline South/148th, Lynnwood-bound track
    "shoreline_north_link_nb":  "40_N17-T1",   # Shoreline North/185th, northbound platform
    "shoreline_south_bay2":     "1_81301",     # Shoreline South/148th Station Bay 2 (Bus 333)
    "shoreline_north_bay3":     "1_81243",     # Shoreline North/185th Station Bay 3 (Bus 348)
}

# Route IDs — verified via OBA API
ROUTES = {
    "1_line":  "40_100479",  # Sound Transit 1 Line
    "2_line":  "40_2LINE",   # Sound Transit 2 Line
    "bus_333": "1_102746",
    "bus_348": "1_100205",
    "bus_44":  "1_100224",
    "bus_45":  "1_100225",
    "bus_372": "1_100214",
}

# ── Line 2 support ─────────────────────────────────────────────────────────────
# Line 2 can be included per request from the UI. Keep the route configured here
# so the backend can merge 1 Line and 2 Line arrivals when requested.
# ──────────────────────────────────────────────────────────────────────────────

# ─── TIMING SETTINGS ─────────────────────────────────────────────────────────
# All values in minutes. Update these when your walk times change.
# Each constant represents one physical leg of the journey.

# ── Leg 1: Odegaard → bus stop or station ─────────────────────────────────────
# Mode 1: walk from Odegaard directly to U-District Station platform
WALK_MODE1_TO_1LINE     = 10   # physical walk to reach the platform
WALK_UDIST_TO_PLATFORM  = 1    # escalator / platform access time from U-District Station concourse

# Mode 2: walk from Odegaard to each bus stop
WALK_TO_44_372          = 5    # to 15th Ave NE & NE Campus Pkwy
WALK_TO_45              = 5    # to W Stevens Way NE & George Washington Ln

# ── Leg 2: bus ride to U-District Station ─────────────────────────────────────
RIDE_44_372_TO_UDIST    = 5    # ride time to U-District Station Bay 1
RIDE_45_TO_UDIST        = 6    # ride time to U-District Station Bay 5

# ── Leg 3: bus drop-off → 1 Line boarding platform ────────────────────────────
WALK_44_372_TO_1LINE    = 3    # Bay 1 → 1 Line platform (escalator + platform walk)
WALK_45_TO_1LINE        = 4    # Bay 5 → 1 Line platform (slightly further)

# ── Leg 4: 1 Line ride ────────────────────────────────────────────────────────
LIGHT_RAIL_TO_SHORELINE_SOUTH = 12  # U-District Station → Shoreline South/148th
LIGHT_RAIL_TO_SHORELINE_NORTH = 15  # U-District Station → Shoreline North/185th

# ── Leg 5: station → final bus bay ────────────────────────────────────────────
WALK_1LINE_TO_333_BAY   = 3    # Shoreline South platform → Bus 333 bay
WALK_1LINE_TO_348_BAY   = 3    # Shoreline North platform → Bus 348 bay
RIDE_333_TO_HOME        = 21   # Bus 333 ride after boarding
WALK_333_TO_HOME        = 4    # Walk from Bus 333 stop to apartment
RIDE_348_TO_HOME        = 5    # Bus 348 ride after boarding
WALK_348_TO_HOME        = 11   # Walk from Bus 348 stop to apartment
DRIVE_GARAGE_TO_HOME    = 10   # Drive home after reaching the train garage

# ── Target transfer buffer at final station ───────────────────────────────────
# How many minutes you want to be at the final station before the bus departs.
TARGET_IDLE_AT_SHORELINE_SOUTH = 7
TARGET_IDLE_AT_SHORELINE_NORTH = 7
# ──────────────────────────────────────────────────────────────────────────────

# Bus stops near Odegaard for Mode 2
BUS_OPTIONS = {
    "bus_44": {
        "label":         "Bus 44",
        "stop_id":       "1_29440",
        "stop_name":     "15th Ave NE & NE Campus Pkwy",
        "route_id":      "1_100224",
        "headsign":      "Ballard Wallingford",
        "walk_to_stop":  WALK_TO_44_372,
        "ride_to_udist": RIDE_44_372_TO_UDIST,
        "walk_to_1line": WALK_44_372_TO_1LINE,
    },
    "bus_372": {
        "label":         "Bus 372",
        "stop_id":       "1_29440",
        "stop_name":     "15th Ave NE & NE Campus Pkwy",
        "route_id":      "1_100214",
        "headsign":      "U-District Station",
        "walk_to_stop":  WALK_TO_44_372,
        "ride_to_udist": RIDE_44_372_TO_UDIST,
        "walk_to_1line": WALK_44_372_TO_1LINE,
    },
    "bus_45": {
        "label":         "Bus 45",
        "stop_id":       "1_75405",         # W Stevens Way NE & George Washington Ln (board)
        "stop_name":     "W Stevens Way NE & George Washington Ln",
        "route_id":      "1_100225",
        "headsign":      "Loyal Heights Greenwood",  # eastbound toward U-District (full route name)
        "dropoff_stop":  "1_9582",          # U-District Station Bay 5 (alight here)
        "walk_to_stop":  WALK_TO_45,
        "ride_to_udist": RIDE_45_TO_UDIST,  # ride time W Stevens Way → Bay 5
        "walk_to_1line": WALK_45_TO_1LINE,
    },
}

MODES = {
    1: {
        "name":        "Walk",
        "description": f"{WALK_MODE1_TO_1LINE} min walk from Odegaard Library → U-District Station platform → 1 Line → Bus 333",
        "bus_options": [],
    },
    2: {
        "name":        "Bus",
        "description": "Bus 44 / 372 from 15th Ave NE & NE Campus Pkwy, or Bus 45 from W Stevens Way NE → U-District Station → 1 Line → Bus 333",
        "bus_options": ["bus_44", "bus_372", "bus_45"],
    },
}

app = FastAPI(title="UW Commute Planner")
app.mount("/static", StaticFiles(directory="static"), name="static")

MAX_OPTIMIZED_RECOMMENDATIONS = 5

DESTINATION_OPTIONS = {
    "333": {
        "label": "Bus 333",
        "short_label": "333",
        "route_id": ROUTES["bus_333"],
        "stop_id": STOPS["shoreline_south_bay2"],
        "headsign": "Mountlake Terrace Station",
        "train_minutes": LIGHT_RAIL_TO_SHORELINE_SOUTH,
        "link_exit_stop_id": STOPS["shoreline_south_link_nb"],
        "station_label": "Shoreline South/148th",
        "transfer_walk": WALK_1LINE_TO_333_BAY,
        "target_idle": TARGET_IDLE_AT_SHORELINE_SOUTH,
        "is_train_only": False,
    },
    "348": {
        "label": "Bus 348",
        "short_label": "348",
        "route_id": ROUTES["bus_348"],
        "stop_id": STOPS["shoreline_north_bay3"],
        "headsign": "Richmond Beach North City",
        "train_minutes": LIGHT_RAIL_TO_SHORELINE_NORTH,
        "link_exit_stop_id": STOPS["shoreline_north_link_nb"],
        "station_label": "Shoreline North/185th",
        "transfer_walk": WALK_1LINE_TO_348_BAY,
        "target_idle": TARGET_IDLE_AT_SHORELINE_NORTH,
        "is_train_only": False,
    },
    "train_north": {
        "label": "Train only",
        "short_label": "Train only",
        "route_id": None,
        "stop_id": None,
        "headsign": None,
        "train_minutes": LIGHT_RAIL_TO_SHORELINE_NORTH,
        "link_exit_stop_id": STOPS["shoreline_north_link_nb"],
        "station_label": "Shoreline North/185th",
        "transfer_walk": 0,
        "target_idle": 0,
        "is_train_only": True,
    },
}


class TrackLegSpec(BaseModel):
    role: str
    label: str
    stop_id: str
    trip_id: str
    service_date: int = Field(..., description="OBA serviceDate")
    route_id: Optional[str] = None

    @field_validator("service_date", mode="before")
    @classmethod
    def coerce_service_date(cls, v):
        return int(v)


class TrackRefreshBody(BaseModel):
    legs: list[TrackLegSpec]
    transfer_walk_mins: int = 0
    is_train_only: bool = False
    final_bus_label: Optional[str] = None


async def get_arrivals(stop_id: str, minutes_after: int = 90) -> list:
    url    = f"{OBA_BASE}/arrivals-and-departures-for-stop/{stop_id}.json"
    params = {"key": API_KEY, "minutesAfter": minutes_after, "minutesBefore": 0}
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
    return resp.json().get("data", {}).get("entry", {}).get("arrivalsAndDepartures", [])


def planner_fetch_horizon(offset_minutes: int, window_mode: str) -> int:
    """
    Choose a practical search horizon for planner lookups.

    offset_minutes: for `within`, the departure window width; for `after`, minutes from now
    until the earliest acceptable leave time.

    We need extra room beyond that offset so the planner can still:
    - find later trains/final buses for `after`
    - show nearby fallback options for `within`
    - account for train travel and transfer timing
    """
    buffer_minutes = 90 if window_mode == "within" else 120
    return max(240, min(360, offset_minutes + buffer_minutes))


def parse_leave_after_hhmm(now: datetime, raw: str) -> tuple[Optional[datetime], Optional[str]]:
    """Interpret HH:MM in Seattle local time; first occurrence strictly after `now`."""
    text = (raw or "").strip()
    if not text:
        return None, "Leave-after time is required (use HH:MM, 24-hour)."
    parts = text.split(":")
    if len(parts) != 2:
        return None, "Leave-after time must be HH:MM (24-hour)."
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError:
        return None, "Leave-after time must be HH:MM (24-hour)."
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None, "Leave-after time must be HH:MM (24-hour)."
    boundary = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if boundary <= now:
        boundary += timedelta(days=1)
    return boundary, None


async def trip_serves_stop(trip_id: str, service_date: int, stop_id: str) -> bool:
    url = f"{OBA_BASE}/trip-details/{trip_id}.json"
    params = {"key": API_KEY, "serviceDate": service_date}
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()

    stop_times = (
        resp.json()
        .get("data", {})
        .get("entry", {})
        .get("schedule", {})
        .get("stopTimes", [])
    )
    return any(stop_time.get("stopId") == stop_id for stop_time in stop_times)


def by_route(arrivals: list, route_id: str) -> list:
    return [a for a in arrivals if a.get("routeId") == route_id]


def by_route_label(arrivals: list, route_id: str, short_name: str) -> list:
    return [
        a for a in arrivals
        if a.get("routeId") == route_id or str(a.get("routeShortName", "")).strip() == short_name
    ]


def by_short_name(arrivals: list, short_name: str) -> list:
    return [
        a for a in arrivals
        if str(a.get("routeShortName", "")).strip() == short_name
    ]


def depart_time(a: dict) -> datetime:
    predicted = a.get("predictedDepartureTime", 0)
    scheduled = a.get("scheduledDepartureTime", 0)
    ts = predicted if predicted > 0 else scheduled
    return datetime.fromtimestamp(ts / 1000, tz=SEATTLE)


def find_arrival_row(
    arrivals: list,
    trip_id: str,
    service_date: int,
    route_id: Optional[str],
) -> Optional[dict]:
    for a in arrivals:
        if a.get("tripId") != trip_id:
            continue
        sd = a.get("serviceDate")
        if sd is None or int(sd) != int(service_date):
            continue
        if route_id and a.get("routeId") != route_id:
            continue
        return a
    return None


def platform_arrival_time(a: dict) -> datetime:
    """Predicted or scheduled arrival at a platform (for alighting)."""
    predicted = a.get("predictedArrivalTime", 0)
    scheduled = a.get("scheduledArrivalTime", 0)
    ts = predicted if predicted > 0 else scheduled
    return datetime.fromtimestamp(ts / 1000, tz=SEATTLE)


def index_link_arrivals_by_trip(arrivals: list, route_ids: set) -> dict:
    """Map (tripId, serviceDate) → row from Link arrivals at the Shoreline exit platform."""
    out = {}
    for a in arrivals:
        if a.get("routeId") not in route_ids:
            continue
        tid = a.get("tripId")
        sd = a.get("serviceDate")
        if tid is None or sd is None:
            continue
        out[(tid, sd)] = a
    return out


def build_connection_tracking(
    destination: str,
    final_cfg: dict,
    train: dict,
    last_bus: Optional[dict],
    feeder_pick: Optional[dict] = None,
) -> dict:
    """Identifiers for POST /api/track/refresh — live boards keyed by tripId + serviceDate."""
    legs = []
    tid = train.get("tripId")
    sd = train.get("serviceDate")
    if tid is not None and sd is not None:
        legs.append(
            {
                "role": "link_udist",
                "label": "Link — U District (departure)",
                "stop_id": STOPS["u_district_station"],
                "trip_id": tid,
                "service_date": sd,
                "route_id": train.get("routeId"),
            }
        )
        legs.append(
            {
                "role": "link_exit",
                "label": f"Link — {final_cfg['station_label']} (arrival)",
                "stop_id": final_cfg["link_exit_stop_id"],
                "trip_id": tid,
                "service_date": sd,
                "route_id": train.get("routeId"),
            }
        )
    if (
        last_bus
        and not last_bus.get("train_only")
        and last_bus.get("tripId")
        and last_bus.get("serviceDate") is not None
        and final_cfg.get("stop_id")
    ):
        legs.append(
            {
                "role": "final_bus",
                "label": f"{final_cfg['label']} — bay departure",
                "stop_id": final_cfg["stop_id"],
                "trip_id": last_bus["tripId"],
                "service_date": last_bus["serviceDate"],
                "route_id": last_bus.get("routeId"),
            }
        )
    if (
        feeder_pick
        and feeder_pick.get("trip_id")
        and feeder_pick.get("service_date") is not None
        and feeder_pick.get("stop_id")
    ):
        legs.append(
            {
                "role": "feeder",
                "label": f"{feeder_pick['label']} — board",
                "stop_id": feeder_pick["stop_id"],
                "trip_id": feeder_pick["trip_id"],
                "service_date": feeder_pick["service_date"],
                "route_id": feeder_pick.get("route_id"),
            }
        )
    return {
        "destination": destination,
        "transfer_walk_mins": final_cfg["transfer_walk"],
        "is_train_only": final_cfg["is_train_only"],
        "station_label": final_cfg["station_label"],
        "final_bus_label": final_cfg.get("label"),
        "legs": legs,
    }


def shoreline_arrival_for_train(
    train_udist: dict,
    exit_by_trip: dict,
    fallback_minutes: int,
    train_departs: datetime,
) -> datetime:
    """Use OBA prediction at the Link exit platform when trip IDs match; else schedule offset."""
    tid = train_udist.get("tripId")
    sd = train_udist.get("serviceDate")
    if tid is None or sd is None:
        return train_departs + timedelta(minutes=fallback_minutes)
    exit_row = exit_by_trip.get((tid, sd))
    if not exit_row:
        return train_departs + timedelta(minutes=fallback_minutes)
    return platform_arrival_time(exit_row)


def fmt(dt: datetime) -> str:
    return dt.strftime("%I:%M %p")


def entry_signature(entry: dict) -> tuple:
    return (
        entry.get("leave_odegaard"),
        entry.get("mode"),
        entry.get("destination_label"),
        tuple(
            (
                step.get("icon"),
                step.get("label"),
                step.get("depart"),
                step.get("arrive"),
                step.get("wait_after"),
            )
            for step in entry.get("steps", [])
        ),
    )


def headsign_matches(expected: Optional[str], actual: str) -> bool:
    if not expected:
        return True
    actual_l = (actual or "").lower()
    expected_l = expected.lower()
    if any(token in expected_l for token in ("university district", "u-district station", "udistrict station")):
        return "university" in actual_l or "u-district" in actual_l or "udistrict" in actual_l
    if expected_l == "richmond beach north city":
        return "richmond beach north city" in actual_l or "hillwood park north city" in actual_l
    return expected_l in actual_l


def headsign_warning(route_label: str, expected: Optional[str], actual: str) -> Optional[str]:
    if not expected or headsign_matches(expected, actual):
        return None
    actual_clean = (actual or "").strip() or "an unexpected destination"
    return f"{route_label} headsign shows “{actual_clean}”, expected “{expected}”. Check direction before boarding."


def format_departure_entry(a: dict, route_label: str, stop_label: str, now: datetime, destination_label: Optional[str] = None) -> dict:
    departs = depart_time(a)
    minutes_until = max(0, int((departs - now).total_seconds() / 60))
    return {
        "route": route_label,
        "stop": stop_label,
        "destination": destination_label or a.get("tripHeadsign", "").strip() or route_label,
        "depart": fmt(departs),
        "depart_ts": departs.timestamp(),
        "minutes_until": minutes_until,
        "status": "Live" if a.get("predicted", False) else "Scheduled",
        "is_realtime": a.get("predicted", False),
    }


def dedupe_departure_rows(rows: list[dict]) -> list[dict]:
    unique = []
    seen = set()
    for row in rows:
        signature = (
            row.get("route"),
            row.get("stop"),
            row.get("destination"),
            row.get("depart"),
        )
        if signature in seen:
            continue
        seen.add(signature)
        unique.append(row)
    return unique


async def best_bus(
    bus_key: str,
    must_arrive_udist_by: datetime,
    now: datetime,
    start_buffer: int = 0,
    minutes_after: int = 90,
) -> Optional[dict]:
    cfg = BUS_OPTIONS[bus_key]
    short_name = cfg["label"].replace("Bus ", "")
    arrivals = by_route_label(await get_arrivals(cfg["stop_id"], minutes_after), cfg["route_id"], short_name)

    pick = None
    pick_warning = None
    pick_score = None
    for a in arrivals:
        d = depart_time(a)
        # Must arrive at U-District Station in time to reach the 1 Line platform
        if d + timedelta(minutes=cfg["ride_to_udist"] + cfg["walk_to_1line"]) > must_arrive_udist_by:
            continue
        required_start_time = cfg["walk_to_stop"] + start_buffer
        if d < now + timedelta(minutes=required_start_time):
            continue
        if cfg.get("dropoff_stop"):
            trip_id = a.get("tripId")
            service_date = a.get("serviceDate")
            if not trip_id or service_date is None:
                continue
            if not await trip_serves_stop(trip_id, service_date, cfg["dropoff_stop"]):
                continue
        matched_headsign = headsign_matches(cfg["headsign"], a.get("tripHeadsign", ""))
        score = (1 if matched_headsign else 0, d.timestamp())
        if pick_score is None or score > pick_score:
            pick = a
            pick_score = score
            pick_warning = headsign_warning(cfg["label"], cfg["headsign"], a.get("tripHeadsign", ""))

    if not pick:
        return None

    d = depart_time(pick)
    arrive_1line = d + timedelta(minutes=cfg["ride_to_udist"] + cfg["walk_to_1line"])
    return {
        "bus_key":       bus_key,
        "label":         cfg["label"],
        "stop_name":     cfg["stop_name"],
        "stop_id":       cfg["stop_id"],
        "trip_id":       pick.get("tripId"),
        "service_date":  pick.get("serviceDate"),
        "route_id":      pick.get("routeId"),
        "walk_to_stop":  cfg["walk_to_stop"],
        "start_buffer_mins": start_buffer,
        "walk_to_1line": cfg["walk_to_1line"],
        "leave_odegaard":d - timedelta(minutes=cfg["walk_to_stop"] + start_buffer),
        "bus_departs":   d,
        "arrive_udist":  d + timedelta(minutes=cfg["ride_to_udist"]),
        "arrive_1line":  arrive_1line,
        "is_realtime":   pick.get("predicted", False),
        "warnings":      [pick_warning] if pick_warning else [],
    }


async def find_connections(
    mode: int,
    now: Optional[datetime] = None,
    stay_window: int = 30,
    start_buffer: int = 0,
    window_mode: str = "within",
    include_line2: bool = True,
    destination: str = "333",
    start: str = "odegaard",
    leave_after: Optional[str] = None,
) -> dict:
    """
    stay_window: for `within`, minutes wide the departure window is; for legacy `after`
    (no leave_after), minutes after now before you are willing to leave.

    leave_after: optional HH:MM (24-hour, America/Los_Angeles). When window_mode is `after`
    and this is set, the earliest acceptable leave time is the next occurrence of that clock time.

    Returns connections whose leave time matches the window, ranked by least idle time at Shoreline South.
    For `within`, falls back to nearest connection outside the window if none exist within it.
    """
    if now is None:
        now = datetime.now(SEATTLE)

    cfg = MODES.get(mode)
    if not cfg:
        return {"error": f"Unknown mode {mode}"}
    final_cfg = DESTINATION_OPTIONS.get(destination)
    if not final_cfg:
        return {"error": f"Unknown destination {destination}"}
    if start not in {"odegaard", "u_district_station"}:
        return {"error": f"Unknown start {start}"}
    if window_mode not in {"within", "after"}:
        return {"error": f"Unknown window mode {window_mode}"}
    if start_buffer < 0 or start_buffer > 60:
        return {"error": f"Unknown start buffer {start_buffer}"}

    leave_after_clean = (leave_after or "").strip()
    stay_window_response = stay_window

    if window_mode == "within":
        if stay_window < 1 or stay_window > 240:
            return {"error": f"Stay window must be between 1 and 240 minutes (got {stay_window})."}
        window_boundary = now + timedelta(minutes=stay_window)
        fetch_horizon = planner_fetch_horizon(stay_window, window_mode)
    elif leave_after_clean:
        window_boundary, parse_err = parse_leave_after_hhmm(now, leave_after_clean)
        if parse_err:
            return {"error": parse_err}
        offset_minutes = max(0, int((window_boundary - now).total_seconds() / 60))
        fetch_horizon = planner_fetch_horizon(offset_minutes, window_mode)
        stay_window_response = offset_minutes
    else:
        if stay_window < 1 or stay_window > 240:
            return {"error": f"After delay must be between 1 and 240 minutes (got {stay_window})."}
        window_boundary = now + timedelta(minutes=stay_window)
        fetch_horizon = planner_fetch_horizon(stay_window, window_mode)

    line_label = "1 Line / 2 Line" if include_line2 else "1 Line"
    if start == "u_district_station":
        final_desc = final_cfg["station_label"] if final_cfg["is_train_only"] else final_cfg["label"]
        mode_description = f"U-District Station platform → {line_label} → {final_desc}"
    else:
        if final_cfg["is_train_only"]:
            if mode == 1:
                mode_description = f"{WALK_MODE1_TO_1LINE} min walk from Odegaard Library → U-District Station platform → {line_label} → {final_cfg['station_label']}"
            else:
                mode_description = f"Bus 44 / 372 from 15th Ave NE & NE Campus Pkwy, or Bus 45 from W Stevens Way NE → U-District Station → {line_label} → {final_cfg['station_label']}"
        else:
            mode_description = (
                cfg["description"]
                .replace("1 Line", line_label)
                .replace("Bus 333", final_cfg["label"])
            )

    results_in_window  = []  # connections within stay window
    results_outside    = []  # fallback: best connections outside window

    def matches_window(dt: datetime) -> bool:
        return dt <= window_boundary if window_mode == "within" else dt >= window_boundary

    link_route_ids = {ROUTES["1_line"], ROUTES["2_line"]} if include_line2 else {ROUTES["1_line"]}

    try:
        if final_cfg["is_train_only"]:
            raw_arrivals, link_exit_arrivals = await asyncio.gather(
                get_arrivals(STOPS["u_district_station"], fetch_horizon),
                get_arrivals(final_cfg["link_exit_stop_id"], fetch_horizon),
            )
            final_bus_arrivals = [{"train_only": True}]
            using_fallback_final_bus = False
        else:
            raw_arrivals, link_exit_arrivals, final_bus_raw = await asyncio.gather(
                get_arrivals(STOPS["u_district_station"], fetch_horizon),
                get_arrivals(final_cfg["link_exit_stop_id"], fetch_horizon),
                get_arrivals(final_cfg["stop_id"], fetch_horizon),
            )
            final_bus_arrivals = by_route_label(
                final_bus_raw,
                final_cfg["route_id"],
                final_cfg["label"].replace("Bus ", ""),
            )
            matched_final_bus_arrivals = [
                a for a in final_bus_arrivals
                if headsign_matches(final_cfg["headsign"], a.get("tripHeadsign", ""))
            ]
            using_fallback_final_bus = bool(final_bus_arrivals) and not matched_final_bus_arrivals
            final_bus_arrivals = matched_final_bus_arrivals or final_bus_arrivals

            if not final_bus_arrivals:
                return {"error": f"No {final_cfg['label']} departures found in the next {fetch_horizon} min."}

        exit_by_trip = index_link_arrivals_by_trip(link_exit_arrivals, link_route_ids)
        trains_1line = by_route(raw_arrivals, ROUTES["1_line"])
        trains_2line = by_route(raw_arrivals, ROUTES["2_line"]) if include_line2 else []
        all_trains   = sorted(trains_1line + trains_2line, key=lambda t: depart_time(t))

        for last_bus in final_bus_arrivals:
            final_bus_warning = None
            if final_cfg["is_train_only"]:
                last_bus_departs = None
            else:
                last_bus_departs = depart_time(last_bus)
                final_bus_warning = headsign_warning(final_cfg["label"], final_cfg["headsign"], last_bus.get("tripHeadsign", "")) if using_fallback_final_bus else None

            def rail_connects_to_final_bus(arrive_shoreline: datetime) -> bool:
                if last_bus_departs is None:
                    return True
                return arrive_shoreline + timedelta(minutes=final_cfg["transfer_walk"]) <= last_bus_departs

            if start == "u_district_station":
                train = None
                best_score = None
                for t in all_trains:
                    t_departs = depart_time(t)
                    if t_departs < now + timedelta(minutes=WALK_UDIST_TO_PLATFORM + start_buffer):
                        continue
                    t_arrive_shoreline = shoreline_arrival_for_train(
                        t, exit_by_trip, final_cfg["train_minutes"], t_departs,
                    )
                    if not rail_connects_to_final_bus(t_arrive_shoreline):
                        continue
                    idle_secs = (last_bus_departs - t_arrive_shoreline).total_seconds() if last_bus_departs else 0
                    score = (idle_secs, t_departs.timestamp(), t_arrive_shoreline.timestamp())
                    if best_score is None or score < best_score:
                        best_score = score
                        train = t
                if not train:
                    continue

                train_departs = depart_time(train)
                leave_station = train_departs - timedelta(minutes=WALK_UDIST_TO_PLATFORM + start_buffer)
                arrive_shoreline = shoreline_arrival_for_train(
                    train, exit_by_trip, final_cfg["train_minutes"], train_departs,
                )
                total_mins_station = int(((last_bus_departs or arrive_shoreline) - leave_station).total_seconds() / 60)
                actual_idle_station = int(((last_bus_departs or arrive_shoreline) - arrive_shoreline).total_seconds() / 60)
                transfer_cushion_station = actual_idle_station - final_cfg["transfer_walk"]
                in_window_station = matches_window(leave_station)
                entry = {
                    "leave_odegaard":  fmt(leave_station),
                    "leave_sort_ts":   leave_station.timestamp(),
                    "minutes_until":   max(0, int((leave_station - now).total_seconds() / 60)),
                    "total_mins":      total_mins_station,
                    "transfer_wait_mins": actual_idle_station,
                    "transfer_cushion_mins": transfer_cushion_station,
                    "transfer_station_label": final_cfg["station_label"],
                    "transfer_walk_mins": final_cfg["transfer_walk"],
                    "walk_hint":       None,
                    "is_realtime":     train.get("predicted", False),
                    "mode":            1,
                    "start":           start,
                    "primary_action_label": "Head to platform",
                    "destination_label": final_cfg["label"] if not final_cfg["is_train_only"] else final_cfg["station_label"],
                    "start_buffer_mins": start_buffer,
                    "warnings": [final_bus_warning] if final_bus_warning else [],
                    "steps": [
                        {"icon": "walk", "label": "Walk to U-District Station platform",
                         "depart": fmt(leave_station), "arrive": fmt(train_departs),
                         "wait_after": None},
                        {"icon": "rail", "label": f"{'1 Line' if train in trains_1line else '2 Line'} → Lynnwood",
                         "depart": fmt(train_departs), "arrive": fmt(arrive_shoreline),
                         "wait_after": int(((last_bus_departs or arrive_shoreline) - arrive_shoreline).total_seconds() / 60) if not final_cfg["is_train_only"] else None},
                    ]
                }
                if final_cfg["is_train_only"]:
                    entry["steps"].append(
                        {"icon": "walk", "label": f"Arrive {final_cfg['station_label']}",
                         "depart": None, "arrive": fmt(arrive_shoreline), "wait_after": None}
                    )
                else:
                    entry["steps"].append(
                        {"icon": "bus",  "label": f"{final_cfg['label']} → Home",
                         "depart": fmt(last_bus_departs), "arrive": None, "wait_after": None}
                    )
                entry["tracking"] = build_connection_tracking(destination, final_cfg, train, last_bus)
                if in_window_station:
                    results_in_window.append((actual_idle_station, entry))
                else:
                    results_outside.append((actual_idle_station, entry))

            elif mode == 1:
                train = None
                best_score = None
                for t in all_trains:
                    t_departs = depart_time(t)
                    t_arrive_shoreline = shoreline_arrival_for_train(
                        t, exit_by_trip, final_cfg["train_minutes"], t_departs,
                    )
                    if not rail_connects_to_final_bus(t_arrive_shoreline):
                        continue
                    idle_secs = (last_bus_departs - t_arrive_shoreline).total_seconds() if last_bus_departs else 0
                    # Score: minimize wait at final station, tiebreak: earlier departure.
                    score = (idle_secs, t_departs.timestamp(), t_arrive_shoreline.timestamp())
                    if best_score is None or score < best_score:
                        best_score = score
                        train = t
                if not train:
                    continue

                train_departs = depart_time(train)
                arrive_shoreline = shoreline_arrival_for_train(
                    train, exit_by_trip, final_cfg["train_minutes"], train_departs,
                )
                leave = train_departs - timedelta(minutes=WALK_MODE1_TO_1LINE + start_buffer)
                if leave < now - timedelta(minutes=1):
                    continue
                total_mins_m1 = int((((last_bus_departs or arrive_shoreline)) - leave).total_seconds() / 60)
                actual_idle_m1 = int((((last_bus_departs or arrive_shoreline)) - arrive_shoreline).total_seconds() / 60)
                transfer_cushion_m1 = actual_idle_m1 - final_cfg["transfer_walk"]
                in_window_m1 = matches_window(leave)
                entry = {
                    "leave_odegaard":  fmt(leave),
                    "leave_sort_ts":   leave.timestamp(),
                    "minutes_until":   max(0, int((leave - now).total_seconds() / 60)),
                    "total_mins":      total_mins_m1,
                    "transfer_wait_mins": actual_idle_m1,
                    "transfer_cushion_mins": transfer_cushion_m1,
                    "transfer_station_label": final_cfg["station_label"],
                    "transfer_walk_mins": final_cfg["transfer_walk"],
                    "walk_hint":       None,
                    "is_realtime":     train.get("predicted", False),
                    "mode":            1,
                    "start":           start,
                    "primary_action_label": "Leave Odegaard Library",
                    "destination_label": final_cfg["label"] if not final_cfg["is_train_only"] else final_cfg["station_label"],
                    "start_buffer_mins": start_buffer,
                    "warnings": [final_bus_warning] if final_bus_warning else [],
                    "steps": [
                        {"icon": "walk", "label": "Walk to U-District Station platform",
                         "depart": fmt(leave), "arrive": fmt(train_departs),
                         "wait_after": None},
                        {"icon": "rail", "label": f"{'1 Line' if train in trains_1line else '2 Line'} → Lynnwood",
                         "depart": fmt(train_departs), "arrive": fmt(arrive_shoreline),
                         "wait_after": int((((last_bus_departs or arrive_shoreline)) - arrive_shoreline).total_seconds() / 60) if not final_cfg["is_train_only"] else None},
                    ]
                }
                if final_cfg["is_train_only"]:
                    entry["steps"].append(
                        {"icon": "walk", "label": f"Arrive {final_cfg['station_label']}",
                         "depart": None, "arrive": fmt(arrive_shoreline), "wait_after": None}
                    )
                else:
                    entry["steps"].append(
                        {"icon": "bus",  "label": f"{final_cfg['label']} → Home",
                         "depart": fmt(last_bus_departs), "arrive": None, "wait_after": None}
                    )
                entry["tracking"] = build_connection_tracking(destination, final_cfg, train, last_bus)
                if in_window_m1:
                    results_in_window.append((actual_idle_m1, entry))
                else:
                    results_outside.append((actual_idle_m1, entry))

            elif mode == 2:
                best_combo = None
                best_score = None
                for t in all_trains:
                    train_departs = depart_time(t)
                    arrive_shoreline = shoreline_arrival_for_train(
                        t, exit_by_trip, final_cfg["train_minutes"], train_departs,
                    )
                    if not rail_connects_to_final_bus(arrive_shoreline):
                        continue
                    shoreline_wait_secs = (last_bus_departs - arrive_shoreline).total_seconds() if last_bus_departs else 0

                    for bk in cfg["bus_options"]:
                        r = await best_bus(
                            bk,
                            train_departs,
                            now,
                            start_buffer=start_buffer,
                            minutes_after=fetch_horizon,
                        )
                        if r is None:
                            continue
                        if r["leave_odegaard"] < now - timedelta(minutes=1):
                            continue
                        # Critical: bus must arrive at 1 Line platform before train departs
                        if r["arrive_1line"] > train_departs:
                            continue

                        transfer_wait_secs = max(0, (train_departs - r["arrive_1line"]).total_seconds())
                        # Score: minimize Shoreline South wait first, then other transfer wait,
                        # then prefer the earlier viable departure from Odegaard.
                        score = (
                            shoreline_wait_secs,
                            transfer_wait_secs,
                            r["leave_odegaard"].timestamp(),
                            train_departs.timestamp(),
                        )
                        if best_score is None or score < best_score:
                            best_score = score
                            best_combo = (t, r, arrive_shoreline)

                if not best_combo:
                    continue

                train, pick, arrive_shoreline = best_combo
                train_departs = depart_time(train)
                arrive_shoreline = shoreline_arrival_for_train(
                    train, exit_by_trip, final_cfg["train_minutes"], train_departs,
                )

                leave = pick["leave_odegaard"]
                total_mins_m2 = int((((last_bus_departs or arrive_shoreline)) - leave).total_seconds() / 60)
                actual_idle_m2 = int((((last_bus_departs or arrive_shoreline)) - arrive_shoreline).total_seconds() / 60)
                transfer_cushion_m2 = actual_idle_m2 - final_cfg["transfer_walk"]
                in_window_m2 = matches_window(leave)

                # Walk hint: if walking would let you leave closer to now with similar or less idle time
                walk_leave = train_departs - timedelta(minutes=WALK_MODE1_TO_1LINE + start_buffer)
                walk_mins_until = int((walk_leave - now).total_seconds() / 60)
                walk_hint = None
                if walk_mins_until >= -1:  # walk departure is still achievable
                    walk_idle = int((last_bus_departs - arrive_shoreline).total_seconds() / 60)
                    walk_hint = f"Walking now gives similar connection with {walk_idle} min at {final_cfg['station_label']}" if walk_mins_until <= 2 else None

                entry2 = {
                    "leave_odegaard": fmt(leave),
                    "leave_sort_ts":  leave.timestamp(),
                    "minutes_until":  max(0, int((leave - now).total_seconds() / 60)),
                    "total_mins":     total_mins_m2,
                    "transfer_wait_mins": actual_idle_m2,
                    "transfer_cushion_mins": transfer_cushion_m2,
                    "transfer_station_label": final_cfg["station_label"],
                    "transfer_walk_mins": final_cfg["transfer_walk"],
                    "walk_hint":      walk_hint,
                    "is_realtime":    pick["is_realtime"] or train.get("predicted", False),
                    "mode":           2,
                    "start":          start,
                    "primary_action_label": "Leave Odegaard Library",
                    "destination_label": final_cfg["label"] if not final_cfg["is_train_only"] else final_cfg["station_label"],
                    "start_buffer_mins": start_buffer,
                    "warnings": [*pick.get("warnings", []), *([final_bus_warning] if final_bus_warning else [])],
                    "steps": [
                        {"icon": "bus",  "label": f"{pick['label']} from {pick['stop_name']}",
                         "depart": fmt(pick["bus_departs"]), "arrive": fmt(pick["arrive_udist"]),
                         "wait_after": None},
                        {"icon": "walk", "label": "Walk to 1 Line platform",
                         "depart": fmt(pick["arrive_udist"]), "arrive": fmt(pick["arrive_1line"]),
                         "wait_after": max(0, int((train_departs - pick["arrive_1line"]).total_seconds() / 60))},
                        {"icon": "rail", "label": f"{'1 Line' if train in trains_1line else '2 Line'} → Lynnwood",
                         "depart": fmt(train_departs),       "arrive": fmt(arrive_shoreline),
                         "wait_after": int((((last_bus_departs or arrive_shoreline)) - arrive_shoreline).total_seconds() / 60) if not final_cfg["is_train_only"] else None},
                    ]
                }
                if final_cfg["is_train_only"]:
                    entry2["steps"].append(
                        {"icon": "walk",  "label": f"Arrive {final_cfg['station_label']}",
                         "depart": None, "arrive": fmt(arrive_shoreline)}
                    )
                else:
                    entry2["steps"].append(
                        {"icon": "bus",  "label": f"{final_cfg['label']} → Home",
                         "depart": fmt(last_bus_departs),        "arrive": None}
                    )
                entry2["tracking"] = build_connection_tracking(destination, final_cfg, train, last_bus, feeder_pick=pick)
                if in_window_m2:
                    results_in_window.append((actual_idle_m2, entry2))
                else:
                    results_outside.append((actual_idle_m2, entry2))

            # For "within", we can stop once we have a small pool of near-term candidates
            # plus nearby fallbacks. For "after", we must keep scanning until we find
            # enough in-window later departures, otherwise earlier trips can crowd out
            # the search before we ever reach the requested threshold.
            if window_mode == "within":
                if len(results_in_window) + len(results_outside) >= 6:
                    break
            else:
                if len(results_in_window) >= MAX_OPTIMIZED_RECOMMENDATIONS:
                    break

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 429:
            return {"error": "rate_limit"}
        return {"error": f"API error: {e.response.status_code}"}
    except httpx.HTTPError as e:
        return {"error": f"Network error: {str(e)}"}

    # Sort optimized candidates by least final wait, then supplement with fallback
    # options if the active window does not produce two distinct recommendations.
    results_in_window.sort(key=lambda x: x[0])
    results_outside.sort(key=lambda x: x[0])

    def dedupe_results(items: list[tuple[int, dict]]) -> list[tuple[int, dict]]:
        unique = []
        seen = set()
        for score, entry in items:
            signature = entry_signature(entry)
            if signature in seen:
                continue
            seen.add(signature)
            unique.append((score, entry))
        return unique

    results_in_window = dedupe_results(results_in_window)
    results_outside = dedupe_results(results_outside)
    optimized = [e for _, e in results_in_window[:MAX_OPTIMIZED_RECOMMENDATIONS]]

    out_of_window_note = None
    if not optimized:
        if window_mode == "within":
            # No connections in window — show best outside with note
            optimized = [e for _, e in results_outside[:MAX_OPTIMIZED_RECOMMENDATIONS]]
            if optimized:
                out_of_window_note = f"No connections found within {stay_window} min departure window — showing nearest available"
        else:
            after_hint = fmt(window_boundary) if leave_after_clean else f"{stay_window} min"
            return {
                "error": f"No viable connections found after {after_hint}. Try an earlier time or a different destination.",
            }
    elif window_mode == "within" and len(optimized) < MAX_OPTIMIZED_RECOMMENDATIONS and results_outside:
        seen_signatures = {entry_signature(item) for item in optimized}
        for _, entry in results_outside:
            signature = entry_signature(entry)
            if signature in seen_signatures:
                continue
            optimized.append(entry)
            seen_signatures.add(signature)
            if len(optimized) == MAX_OPTIMIZED_RECOMMENDATIONS:
                break

    if not optimized:
        return {"error": "No viable connections found. Try refreshing."}

    final = []
    for index, entry in enumerate(optimized[:MAX_OPTIMIZED_RECOMMENDATIONS]):
        final.append({
            **entry,
            "recommendation_type": "best" if index == 0 else "backup",
        })

    candidate_pool = [e for _, e in results_in_window + results_outside]
    seen_departures = {entry_signature(item) for item in final}
    earliest_alternative = None
    earliest_candidate = min(
        candidate_pool,
        key=lambda item: (item.get("leave_sort_ts", float("inf")), item.get("total_mins", 0)),
        default=None,
    )
    if earliest_candidate is not None and entry_signature(earliest_candidate) not in seen_departures:
        earliest_alternative = {
            **earliest_candidate,
            "recommendation_type": "earliest",
            "recommendation_note": "Earliest viable departure — not optimized for connection wait time.",
        }

    if earliest_alternative:
        final.append(earliest_alternative)

    return {
        "mode_description":   mode_description,
        "connections":        final,
        "out_of_window_note": out_of_window_note,
        "stay_window":        stay_window_response,
        "start_buffer":       start_buffer,
        "window_mode":        window_mode,
        "include_line2":      include_line2,
        "destination":        destination,
        "start":              start,
        "leave_after":        leave_after_clean if window_mode == "after" and leave_after_clean else None,
    }


@app.get("/api/connections")
async def get_connections(
    mode: int = 1,
    stay: int = 30,
    start_buffer: int = 0,
    window_mode: str = "within",
    include_line2: bool = True,
    destination: str = "333",
    start: str = "odegaard",
    leave_after: Optional[str] = None,
):
    return await find_connections(
        mode,
        stay_window=stay,
        start_buffer=start_buffer,
        window_mode=window_mode,
        include_line2=include_line2,
        destination=destination,
        start=start,
        leave_after=leave_after,
    )


async def refresh_tracked_plan(body: TrackRefreshBody) -> dict:
    legs_spec = body.legs
    if not legs_spec:
        return {"error": "No legs to refresh"}

    horizon = 270
    stop_ids = sorted({leg.stop_id for leg in legs_spec})
    fetched = await asyncio.gather(*[get_arrivals(sid, horizon) for sid in stop_ids])
    arrivals_by_stop = dict(zip(stop_ids, fetched))

    now = datetime.now(SEATTLE)
    out_legs = []
    link_exit_dt = None
    final_bus_dt = None

    for leg in legs_spec:
        arrivals = arrivals_by_stop.get(leg.stop_id, [])
        row = find_arrival_row(arrivals, leg.trip_id, leg.service_date, leg.route_id)
        entry = {"role": leg.role, "label": leg.label, "found": row is not None}
        if row:
            entry["is_realtime"] = bool(row.get("predicted"))
            if leg.role == "link_exit":
                dt = platform_arrival_time(row)
                entry["time_kind"] = "arrival"
                entry["time_display"] = fmt(dt)
                entry["minutes_until"] = max(0, int((dt - now).total_seconds() / 60))
                link_exit_dt = dt
            else:
                dt = depart_time(row)
                entry["time_kind"] = "departure"
                entry["time_display"] = fmt(dt)
                entry["minutes_until"] = max(0, int((dt - now).total_seconds() / 60))
                if leg.role == "final_bus":
                    final_bus_dt = dt
        else:
            entry["is_realtime"] = False
            entry["time_kind"] = None
            entry["time_display"] = None
            entry["minutes_until"] = None
            entry["note"] = "Not on the live board — trip may have finished or IDs may have changed."
        out_legs.append(entry)

    connection = None
    if body.is_train_only:
        connection = {
            "ok": True,
            "slack_minutes": None,
            "summary": "Train-only plan — no bus connection to check.",
        }
    elif link_exit_dt and final_bus_dt:
        slack = (final_bus_dt - link_exit_dt).total_seconds() / 60.0 - body.transfer_walk_mins
        bus_lbl = body.final_bus_label or "Bus"
        ok = slack >= -0.25
        connection = {
            "ok": ok,
            "slack_minutes": round(slack, 1),
            "summary": (
                f"{bus_lbl} leaves about {slack:.1f} min after Link arrives at platform "
                f"(you budget ~{body.transfer_walk_mins} min walk to the bay)."
                if ok
                else (
                    f"Tight or missed: about {slack:.1f} min after Link arrives vs "
                    f"~{body.transfer_walk_mins} min walk — recheck times or replan."
                )
            ),
        }
    else:
        missing = []
        if not link_exit_dt:
            missing.append("Link arrival at Shoreline platform")
        if not body.is_train_only and not final_bus_dt:
            missing.append(body.final_bus_label or "final bus")
        connection = {
            "ok": None,
            "slack_minutes": None,
            "summary": "Could not refresh the full chain (" + ", ".join(missing) + "). Try again shortly.",
        }

    return {"report_time": fmt(now), "legs": out_legs, "connection": connection}


@app.post("/api/track/refresh")
async def post_track_refresh(body: TrackRefreshBody):
    try:
        return await refresh_tracked_plan(body)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 429:
            return {"error": "rate_limit"}
        return {"error": f"API error: {e.response.status_code}"}
    except httpx.HTTPError as e:
        return {"error": f"Network error: {str(e)}"}


@app.get("/api/modes")
async def get_modes():
    return {"modes": [{"id": k, "name": v["name"], "description": v["description"]} for k, v in MODES.items()]}

@app.get("/api/timings")
async def get_timings(destination: str = "333", include_line2: bool = True):
    """Returns all timing constants so the frontend can display them without hardcoding."""
    final_cfg = DESTINATION_OPTIONS.get(destination, DESTINATION_OPTIONS["333"])
    final_station = final_cfg["station_label"]
    final_label = final_cfg["label"]
    final_train_minutes = final_cfg["train_minutes"]
    line_label = "1 Line / 2 Line" if include_line2 else "1 Line"
    if destination == "333":
        final_legs = [
            {"label": f"Walk {final_station} platform → {final_label} bay", "min": final_cfg["transfer_walk"], "type": "end"},
            {"label": "Bus 333 ride → apartment area", "min": RIDE_333_TO_HOME, "type": "bus"},
            {"label": "Walk to apartment", "min": WALK_333_TO_HOME, "type": "walk2"},
        ]
    elif destination == "348":
        final_legs = [
            {"label": f"Walk {final_station} platform → {final_label} bay", "min": final_cfg["transfer_walk"], "type": "end"},
            {"label": "Bus 348 ride → apartment area", "min": RIDE_348_TO_HOME, "type": "bus"},
            {"label": "Walk to apartment", "min": WALK_348_TO_HOME, "type": "walk2"},
        ]
    else:
        final_legs = [
            {"label": "Walk Shoreline North/185th platform → Bus 348 bay", "min": WALK_1LINE_TO_348_BAY, "type": "end"},
            {"label": "Drive home from train garage", "min": DRIVE_GARAGE_TO_HOME, "type": "bus"},
        ]

    return {
        "mode1": [
            {"label": "Walk Odegaard → 1 Line platform", "min": WALK_MODE1_TO_1LINE,     "type": "walk"},
            {"label": f"{line_label} → {final_station}",                 "min": final_train_minutes, "type": "rail"},
            *final_legs,
        ],
        "bus_44_372": [
            {"label": "Walk Odegaard → stop", "min": WALK_TO_44_372,          "type": "walk"},
            {"label": "Bus 44/372 ride → Bay 1",             "min": RIDE_44_372_TO_UDIST,    "type": "bus"},
            {"label": "Walk Bay 1 → 1 Line platform",        "min": WALK_44_372_TO_1LINE,    "type": "walk2"},
            {"label": f"{line_label} → {final_station}",     "min": final_train_minutes, "type": "rail"},
            *final_legs,
        ],
        "bus_45": [
            {"label": "Walk Odegaard → stop", "min": WALK_TO_45,              "type": "walk"},
            {"label": "Bus 45 ride → Bay 5",                 "min": RIDE_45_TO_UDIST,        "type": "bus"},
            {"label": "Walk Bay 5 → 1 Line platform",        "min": WALK_45_TO_1LINE,        "type": "walk2"},
            {"label": f"{line_label} → {final_station}",     "min": final_train_minutes, "type": "rail"},
            *final_legs,
        ],
        "final_label": final_label,
        "final_station_label": final_station,
        "line_label": line_label,
        "is_train_only": final_cfg["is_train_only"],
    }


@app.get("/api/timetable")
async def get_timetable():
    now = datetime.now(SEATTLE)
    timetable_horizon_minutes = 240

    try:
        u_district_arrivals = await get_arrivals(STOPS["u_district_station"], timetable_horizon_minutes)
        shoreline_south_arrivals = await get_arrivals(STOPS["shoreline_south_bay2"], timetable_horizon_minutes)
        shoreline_north_arrivals = await get_arrivals(STOPS["shoreline_north_bay3"], timetable_horizon_minutes)
        feeder_stop_arrivals = await get_arrivals(BUS_OPTIONS["bus_44"]["stop_id"], timetable_horizon_minutes)
        bus_45_arrivals = await get_arrivals(BUS_OPTIONS["bus_45"]["stop_id"], timetable_horizon_minutes)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 429:
            return {"error": "rate_limit"}
        return {"error": f"API error: {e.response.status_code}"}
    except httpx.HTTPError as e:
        return {"error": f"Network error: {str(e)}"}

    link_rows = []
    for route_key, route_label in (("1_line", "1 Line"), ("2_line", "2 Line")):
        for arrival in by_route_label(u_district_arrivals, ROUTES[route_key], "1" if route_key == "1_line" else "2"):
            link_rows.append(format_departure_entry(
                arrival,
                route_label,
                "U-District Station",
                now,
                arrival.get("tripHeadsign", "").strip() or "Northbound",
            ))
    link_rows.sort(key=lambda row: row["depart_ts"])
    link_rows = dedupe_departure_rows(link_rows)

    final_rows = []
    for arrival in by_route_label(shoreline_south_arrivals, ROUTES["bus_333"], "333"):
        final_rows.append(format_departure_entry(
            arrival,
            "Bus 333",
            "Shoreline South/148th Bay 2",
            now,
            arrival.get("tripHeadsign", "").strip(),
        ))
        final_rows[-1]["warning"] = headsign_warning("Bus 333", "Mountlake Terrace Station", arrival.get("tripHeadsign", ""))
    for arrival in by_route_label(shoreline_north_arrivals, ROUTES["bus_348"], "348"):
        if not headsign_matches("Richmond Beach North City", arrival.get("tripHeadsign", "")):
            continue
        final_rows.append(format_departure_entry(
            arrival,
            "Bus 348",
            "Shoreline North/185th Bay 3",
            now,
            arrival.get("tripHeadsign", "").strip(),
        ))
    final_rows.sort(key=lambda row: row["depart_ts"])
    final_rows = dedupe_departure_rows(final_rows)

    feeder_rows = []
    for bus_key in ("bus_44", "bus_372"):
        cfg = BUS_OPTIONS[bus_key]
        short_name = cfg["label"].replace("Bus ", "")
        for arrival in by_route_label(feeder_stop_arrivals, cfg["route_id"], short_name):
            feeder_rows.append(format_departure_entry(
                arrival,
                cfg["label"],
                cfg["stop_name"],
                now,
                arrival.get("tripHeadsign", "").strip(),
            ))
            feeder_rows[-1]["warning"] = headsign_warning(cfg["label"], cfg["headsign"], arrival.get("tripHeadsign", ""))
    cfg_45 = BUS_OPTIONS["bus_45"]
    for arrival in by_route_label(bus_45_arrivals, cfg_45["route_id"], "45"):
        feeder_rows.append(format_departure_entry(
            arrival,
            cfg_45["label"],
            cfg_45["stop_name"],
            now,
            arrival.get("tripHeadsign", "").strip(),
        ))
        feeder_rows[-1]["warning"] = headsign_warning(cfg_45["label"], cfg_45["headsign"], arrival.get("tripHeadsign", ""))
    feeder_rows.sort(key=lambda row: row["depart_ts"])
    feeder_rows = dedupe_departure_rows(feeder_rows)

    class_rows = []
    for arrival in by_short_name(feeder_stop_arrivals, "44"):
        if not headsign_matches("Ballard Wallingford", arrival.get("tripHeadsign", "")):
            continue
        class_rows.append(format_departure_entry(
            arrival,
            "Bus 44",
            BUS_OPTIONS["bus_44"]["stop_name"],
            now,
            arrival.get("tripHeadsign", "").strip(),
        ))
    for arrival in by_short_name(bus_45_arrivals, "67"):
        if not headsign_matches("Northgate Station Roosevelt Station", arrival.get("tripHeadsign", "")):
            continue
        class_rows.append(format_departure_entry(
            arrival,
            "Bus 67",
            BUS_OPTIONS["bus_45"]["stop_name"],
            now,
            arrival.get("tripHeadsign", "").strip(),
        ))
    for arrival in by_short_name(feeder_stop_arrivals, "372"):
        if not headsign_matches("U-District Station", arrival.get("tripHeadsign", "")):
            continue
        class_rows.append(format_departure_entry(
            arrival,
            "Bus 372",
            BUS_OPTIONS["bus_372"]["stop_name"],
            now,
            arrival.get("tripHeadsign", "").strip(),
        ))
    class_rows.sort(key=lambda row: row["depart_ts"])
    class_rows = dedupe_departure_rows(class_rows)

    return {
        "generated_at": now.strftime("%I:%M %p"),
        "tabs": {
            "feeder_buses": {
                "label": "Feeder Buses",
                "help": "Upcoming feeder buses from your Odegaard-area boarding stops.",
                "routes": ["Bus 44", "Bus 45", "Bus 372"],
                "rows": feeder_rows,
                "empty_message": "No upcoming feeder bus departures found right now.",
            },
            "class": {
                "label": "Class",
                "help": "Upcoming class-bound buses. About 10 min to class after boarding, including bus ride and walk.",
                "routes": ["Bus 44", "Bus 67", "Bus 372"],
                "rows": class_rows,
                "empty_message": "No upcoming class-bound departures found right now.",
            },
            "link": {
                "label": "Link",
                "help": "Upcoming northbound train departures from U-District Station.",
                "routes": ["1 Line", "2 Line"],
                "rows": link_rows,
                "empty_message": "No upcoming Link departures found right now.",
            },
            "final_buses": {
                "label": "Final Buses",
                "help": "Upcoming departures from the final transfer stops you care about.",
                "routes": ["Bus 333", "Bus 348"],
                "rows": final_rows,
                "empty_message": "No upcoming 333 or 348 departures found right now.",
            },
        },
    }

@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    with open("static/index.html") as f:
        return f.read()

if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
