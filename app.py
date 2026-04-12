from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import httpx
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

SEATTLE = ZoneInfo("America/Los_Angeles")
from typing import Optional
import uvicorn

# API key — set via environment variable before running:
#   export OBA_API_KEY=your_key_here
# Falls back to "TEST" (shared public key, may hit rate limits occasionally)
# To request your own key: email oba_api_key@soundtransit.org
API_KEY  = os.environ.get("OBA_API_KEY", "TEST")
OBA_BASE = "https://api.pugetsound.onebusaway.org/api/where"

# Stop IDs — verified via OBA stops-for-location API
STOPS = {
    "u_district_station":   "40_990002",  # U-District Station, northbound 1 Line
    "shoreline_south_bay1": "1_81299",    # Shoreline South/148th Station Bay 1
}

# Route IDs — verified via OBA API
ROUTES = {
    "1_line":  "40_100479",  # Sound Transit 1 Line
    "2_line":  "40_2LINE",   # Sound Transit 2 Line
    "bus_333": "1_102746",
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
WALK_MODE1_TO_1LINE     = 14   # includes exit library + walk + reach platform

# Mode 2: walk from Odegaard to each bus stop (includes buffer to not miss bus)
WALK_TO_44_372          = 5    # to 15th Ave NE & NE Campus Pkwy
WALK_TO_45              = 8    # to W Stevens Way NE & George Washington Ln

# ── Leg 2: bus ride to U-District Station ─────────────────────────────────────
RIDE_44_372_TO_UDIST    = 5    # ride time to U-District Station Bay 1
RIDE_45_TO_UDIST        = 6    # ride time to U-District Station Bay 5

# ── Leg 3: bus drop-off → 1 Line boarding platform ────────────────────────────
WALK_44_372_TO_1LINE    = 3    # Bay 1 → 1 Line platform (escalator + platform walk)
WALK_45_TO_1LINE        = 4    # Bay 5 → 1 Line platform (slightly further)

# ── Leg 4: 1 Line ride ────────────────────────────────────────────────────────
LIGHT_RAIL_TO_SHORELINE = 12   # U-District Station → Shoreline South/148th

# ── Leg 5: Shoreline South → Bus 333 bay ──────────────────────────────────────
WALK_1LINE_TO_BAY       = 2    # physical walk time: exit 1 Line + reach Bus 333 bay

# ── Target idle time at Shoreline South ───────────────────────────────────────
# How many minutes you want to be at Shoreline South before Bus 333 departs.
# Increase if you keep missing 333. Decrease if you want less waiting.
# Minimum should be WALK_1LINE_TO_BAY (2 min) to physically make the connection.
TARGET_IDLE_AT_SHORELINE = 7
# ──────────────────────────────────────────────────────────────────────────────

# Bus stops near Odegaard for Mode 2
BUS_OPTIONS = {
    "bus_44": {
        "label":         "Bus 44",
        "stop_id":       "1_10914",
        "stop_name":     "15th Ave NE & NE Campus Pkwy",
        "route_id":      "1_100224",
        "headsign":      "university",  # matches both "University Of Washington Medical Center" and "University District"
        "walk_to_stop":  WALK_TO_44_372,     # includes buffer — leave Odegaard this many mins before bus
        "ride_to_udist": RIDE_44_372_TO_UDIST,
        "walk_to_1line": WALK_44_372_TO_1LINE,
    },
    "bus_372": {
        "label":         "Bus 372",
        "stop_id":       "1_10914",
        "stop_name":     "15th Ave NE & NE Campus Pkwy",
        "route_id":      "1_100214",
        "headsign":      "University District",  # toward U-District, not Bothell
        "walk_to_stop":  WALK_TO_44_372,     # includes buffer — leave Odegaard this many mins before bus
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
        "walk_to_stop":  WALK_TO_45,        # includes buffer — leave Odegaard this many mins before bus
        "ride_to_udist": RIDE_45_TO_UDIST,  # ride time W Stevens Way → Bay 5
        "walk_to_1line": WALK_45_TO_1LINE,
    },
}

MODES = {
    1: {
        "name":        "Walk",
        "description": f"{WALK_MODE1_TO_1LINE} min walk from Odegaard → U-District Station platform → 1 Line → Bus 333",
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


async def get_arrivals(stop_id: str, minutes_after: int = 90) -> list:
    url    = f"{OBA_BASE}/arrivals-and-departures-for-stop/{stop_id}.json"
    params = {"key": API_KEY, "minutesAfter": minutes_after, "minutesBefore": 0}
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
    return resp.json().get("data", {}).get("entry", {}).get("arrivalsAndDepartures", [])


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


def depart_time(a: dict) -> datetime:
    predicted = a.get("predictedDepartureTime", 0)
    scheduled = a.get("scheduledDepartureTime", 0)
    ts = predicted if predicted > 0 else scheduled
    return datetime.fromtimestamp(ts / 1000, tz=SEATTLE)


def fmt(dt: datetime) -> str:
    return dt.strftime("%I:%M %p")


async def best_bus(bus_key: str, must_arrive_udist_by: datetime, now: datetime) -> Optional[dict]:
    cfg      = BUS_OPTIONS[bus_key]
    arrivals = by_route(await get_arrivals(cfg["stop_id"]), cfg["route_id"])

    pick = None
    for a in arrivals:
        # Filter to correct direction using headsign
        if cfg["headsign"].lower() not in a.get("tripHeadsign", "").lower():
            continue
        d = depart_time(a)
        # Must arrive at U-District Station in time to reach the 1 Line platform
        if d + timedelta(minutes=cfg["ride_to_udist"] + cfg["walk_to_1line"]) > must_arrive_udist_by:
            continue
        # Must have enough time to walk to the stop (includes buffer)
        if d < now + timedelta(minutes=cfg["walk_to_stop"]):
            continue
        if cfg.get("dropoff_stop"):
            trip_id = a.get("tripId")
            service_date = a.get("serviceDate")
            if not trip_id or service_date is None:
                continue
            if not await trip_serves_stop(trip_id, service_date, cfg["dropoff_stop"]):
                continue
        pick = a  # keep updating — want the latest valid one

    if not pick:
        return None

    d = depart_time(pick)
    arrive_1line = d + timedelta(minutes=cfg["ride_to_udist"] + cfg["walk_to_1line"])
    return {
        "label":         cfg["label"],
        "stop_name":     cfg["stop_name"],
        "walk_to_stop":  cfg["walk_to_stop"],
        "walk_to_1line": cfg["walk_to_1line"],
        "leave_odegaard":d - timedelta(minutes=cfg["walk_to_stop"]),
        "bus_departs":   d,
        "arrive_udist":  d + timedelta(minutes=cfg["ride_to_udist"]),
        "arrive_1line":  arrive_1line,
        "is_realtime":   pick.get("predicted", False),
    }


async def find_connections(
    mode: int,
    now: Optional[datetime] = None,
    stay_window: int = 30,
    include_line2: bool = True,
) -> dict:
    """
    stay_window: how many minutes from now you are willing to stay at Odegaard.
    Returns connections whose leave_odegaard falls within that window,
    ranked by least idle time at Shoreline South.
    Falls back to nearest connection outside the window if none exist within it.
    """
    if now is None:
        now = datetime.now(SEATTLE)

    cfg = MODES.get(mode)
    if not cfg:
        return {"error": f"Unknown mode {mode}"}

    line_label = "1 Line / 2 Line" if include_line2 else "1 Line"
    mode_description = cfg["description"].replace("1 Line", line_label)

    # Latest acceptable departure from Odegaard based on stay window
    window_deadline = now + timedelta(minutes=stay_window)

    # Minimum walk to physically catch 333 from the train
    min_buffer = WALK_1LINE_TO_BAY + LIGHT_RAIL_TO_SHORELINE

    results_in_window  = []  # connections within stay window
    results_outside    = []  # fallback: best connections outside window

    try:
        buses_333    = by_route(await get_arrivals(STOPS["shoreline_south_bay1"], 120), ROUTES["bus_333"])
        raw_arrivals = await get_arrivals(STOPS["u_district_station"], 120)
        trains_1line = by_route(raw_arrivals, ROUTES["1_line"])
        trains_2line = by_route(raw_arrivals, ROUTES["2_line"]) if include_line2 else []
        all_trains   = sorted(trains_1line + trains_2line, key=lambda t: depart_time(t))

        if not buses_333:
            return {"error": "No Bus 333 departures found in the next 2 hours."}

        for b333 in buses_333:
            b333_departs = depart_time(b333)

            # Hard limit: train must board early enough to physically reach 333
            hard_latest_board = b333_departs - timedelta(minutes=min_buffer)

            if mode == 1:
                train = None
                best_score = None
                for t in all_trains:
                    t_departs = depart_time(t)
                    if t_departs > hard_latest_board:
                        continue
                    t_arrive_shoreline = t_departs + timedelta(minutes=LIGHT_RAIL_TO_SHORELINE)
                    idle_secs = (b333_departs - t_arrive_shoreline).total_seconds()
                    # Score: minimize wait at Shoreline South, tiebreak: earlier departure.
                    score = (idle_secs, t_departs.timestamp())
                    if best_score is None or score < best_score:
                        best_score = score
                        train = t
                if not train:
                    continue

                train_departs = depart_time(train)
                arrive_shoreline = train_departs + timedelta(minutes=LIGHT_RAIL_TO_SHORELINE)
                leave = train_departs - timedelta(minutes=WALK_MODE1_TO_1LINE)
                if leave < now - timedelta(minutes=1):
                    continue
                total_mins_m1 = int((b333_departs - leave).total_seconds() / 60)
                actual_idle_m1 = int((b333_departs - arrive_shoreline).total_seconds() / 60)
                in_window_m1 = leave <= window_deadline
                entry = {
                    "leave_odegaard":  fmt(leave),
                    "minutes_until":   max(0, int((leave - now).total_seconds() / 60)),
                    "total_mins":      total_mins_m1,
                    "walk_hint":       None,
                    "is_realtime":     train.get("predicted", False),
                    "mode":            1,
                    "steps": [
                        {"icon": "walk", "label": "Walk to U-District Station platform",
                         "depart": fmt(leave), "arrive": fmt(train_departs),
                         "wait_after": None},
                        {"icon": "rail", "label": f"{'1 Line' if train in trains_1line else '2 Line'} → Lynnwood",
                         "depart": fmt(train_departs), "arrive": fmt(arrive_shoreline),
                         "wait_after": int((b333_departs - arrive_shoreline).total_seconds() / 60)},
                        {"icon": "bus",  "label": "Bus 333 → Home",
                         "depart": fmt(b333_departs), "arrive": None,
                         "wait_after": None},
                    ]
                }
                if in_window_m1:
                    results_in_window.append((actual_idle_m1, entry))
                else:
                    results_outside.append((actual_idle_m1, entry))

            elif mode == 2:
                best_combo = None
                best_score = None
                for t in all_trains:
                    train_departs = depart_time(t)
                    if train_departs > hard_latest_board:
                        continue
                    arrive_shoreline = train_departs + timedelta(minutes=LIGHT_RAIL_TO_SHORELINE)
                    shoreline_wait_secs = (b333_departs - arrive_shoreline).total_seconds()

                    for bk in cfg["bus_options"]:
                        r = await best_bus(bk, train_departs, now)
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

                leave = pick["leave_odegaard"]
                total_mins_m2 = int((b333_departs - leave).total_seconds() / 60)
                actual_idle_m2 = int((b333_departs - arrive_shoreline).total_seconds() / 60)
                in_window_m2 = leave <= window_deadline

                # Walk hint: if walking would let you leave closer to now with similar or less idle time
                walk_leave = train_departs - timedelta(minutes=WALK_MODE1_TO_1LINE)
                walk_mins_until = int((walk_leave - now).total_seconds() / 60)
                walk_hint = None
                if walk_mins_until >= -1:  # walk departure is still achievable
                    walk_idle = int((b333_departs - arrive_shoreline).total_seconds() / 60)
                    walk_hint = f"Walking now gives similar connection with {walk_idle} min at Shoreline South" if walk_mins_until <= 2 else None

                entry2 = {
                    "leave_odegaard": fmt(leave),
                    "minutes_until":  max(0, int((leave - now).total_seconds() / 60)),
                    "total_mins":     total_mins_m2,
                    "walk_hint":      walk_hint,
                    "is_realtime":    pick["is_realtime"] or train.get("predicted", False),
                    "mode":           2,
                    "steps": [
                        {"icon": "bus",  "label": f"{pick['label']} from {pick['stop_name']}",
                         "depart": fmt(pick["bus_departs"]), "arrive": fmt(pick["arrive_udist"]),
                         "wait_after": None},
                        {"icon": "walk", "label": "Walk to 1 Line platform",
                         "depart": fmt(pick["arrive_udist"]), "arrive": fmt(pick["arrive_1line"]),
                         "wait_after": max(0, int((train_departs - pick["arrive_1line"]).total_seconds() / 60))},
                        {"icon": "rail", "label": f"{'1 Line' if train in trains_1line else '2 Line'} → Lynnwood",
                         "depart": fmt(train_departs),       "arrive": fmt(arrive_shoreline),
                         "wait_after": int((b333_departs - arrive_shoreline).total_seconds() / 60)},
                        {"icon": "bus",  "label": "Bus 333 → Home",
                         "depart": fmt(b333_departs),        "arrive": None},
                    ]
                }
                if in_window_m2:
                    results_in_window.append((actual_idle_m2, entry2))
                else:
                    results_outside.append((actual_idle_m2, entry2))

            if len(results_in_window) + len(results_outside) >= 6:
                break

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 429:
            return {"error": "rate_limit"}
        return {"error": f"API error: {e.response.status_code}"}
    except httpx.HTTPError as e:
        return {"error": f"Network error: {str(e)}"}

    # Sort in-window results by least idle time, take top 3
    results_in_window.sort(key=lambda x: x[0])
    final = [e for _, e in results_in_window[:3]]

    out_of_window_note = None
    if not final:
        # No connections in window — show best outside with note
        results_outside.sort(key=lambda x: x[0])
        final = [e for _, e in results_outside[:2]]
        if final:
            out_of_window_note = f"No connections found within {stay_window} min stay window — showing nearest available"

    if not final:
        return {"error": "No viable connections found. Try refreshing."}

    return {
        "mode_description":   mode_description,
        "connections":        final,
        "out_of_window_note": out_of_window_note,
        "stay_window":        stay_window,
        "include_line2":      include_line2,
    }


@app.get("/api/connections")
async def get_connections(mode: int = 1, stay: int = 30, include_line2: bool = True):
    return await find_connections(mode, stay_window=stay, include_line2=include_line2)

@app.get("/api/modes")
async def get_modes():
    return {"modes": [{"id": k, "name": v["name"], "description": v["description"]} for k, v in MODES.items()]}

@app.get("/api/timings")
async def get_timings():
    """Returns all timing constants so the frontend can display them without hardcoding."""
    return {
        "mode1": [
            {"label": "Walk Odegaard → 1 Line platform (incl. buffer)", "min": WALK_MODE1_TO_1LINE,     "type": "walk"},
            {"label": "1 Line → Shoreline South",                        "min": LIGHT_RAIL_TO_SHORELINE, "type": "rail"},
            {"label": f"Walk + planned transfer buffer at Shoreline South ({TARGET_IDLE_AT_SHORELINE} min)", "min": TARGET_IDLE_AT_SHORELINE, "type": "end"},
        ],
        "bus_44_372": [
            {"label": "Walk Odegaard → stop (incl. buffer)", "min": WALK_TO_44_372,          "type": "walk"},
            {"label": "Bus 44/372 ride → Bay 1",             "min": RIDE_44_372_TO_UDIST,    "type": "bus"},
            {"label": "Walk Bay 1 → 1 Line platform",        "min": WALK_44_372_TO_1LINE,    "type": "walk2"},
            {"label": "1 Line → Shoreline South",            "min": LIGHT_RAIL_TO_SHORELINE, "type": "rail"},
            {"label": f"Walk + planned transfer buffer at Shoreline South ({TARGET_IDLE_AT_SHORELINE} min)", "min": TARGET_IDLE_AT_SHORELINE, "type": "end"},
        ],
        "bus_45": [
            {"label": "Walk Odegaard → stop (incl. buffer)", "min": WALK_TO_45,              "type": "walk"},
            {"label": "Bus 45 ride → Bay 5",                 "min": RIDE_45_TO_UDIST,        "type": "bus"},
            {"label": "Walk Bay 5 → 1 Line platform",        "min": WALK_45_TO_1LINE,        "type": "walk2"},
            {"label": "1 Line → Shoreline South",            "min": LIGHT_RAIL_TO_SHORELINE, "type": "rail"},
            {"label": f"Walk + planned transfer buffer at Shoreline South ({TARGET_IDLE_AT_SHORELINE} min)", "min": TARGET_IDLE_AT_SHORELINE, "type": "end"},
        ],
    }

@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    with open("static/index.html") as f:
        return f.read()

if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
