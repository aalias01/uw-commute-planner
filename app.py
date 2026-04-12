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
    "u_district_station":       "40_990002",  # U-District Station, northbound 1 Line
    "shoreline_south_bay2":     "1_81301",    # Shoreline South/148th Station Bay 2
    "shoreline_north_bay3":     "1_81243",    # Shoreline North/185th Station Bay 3
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
LIGHT_RAIL_TO_SHORELINE_SOUTH = 12  # U-District Station → Shoreline South/148th
LIGHT_RAIL_TO_SHORELINE_NORTH = 15  # U-District Station → Shoreline North/185th

# ── Leg 5: station → final bus bay ────────────────────────────────────────────
WALK_1LINE_TO_333_BAY   = 2    # Shoreline South platform → Bus 333 bay
WALK_1LINE_TO_348_BAY   = 3    # Shoreline North platform → Bus 348 bay

# ── Target transfer buffer at final station ───────────────────────────────────
# How many minutes you want to be at the final station before the bus departs.
TARGET_IDLE_AT_SHORELINE_SOUTH = 7
TARGET_IDLE_AT_SHORELINE_NORTH = 7
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

DESTINATION_OPTIONS = {
    "333": {
        "label": "Bus 333",
        "short_label": "333",
        "route_id": ROUTES["bus_333"],
        "stop_id": STOPS["shoreline_south_bay2"],
        "headsign": "Mountlake Terrace Station",
        "train_minutes": LIGHT_RAIL_TO_SHORELINE_SOUTH,
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
        "headsign": "Richmond Beach",
        "train_minutes": LIGHT_RAIL_TO_SHORELINE_NORTH,
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
        "station_label": "Shoreline North/185th",
        "transfer_walk": 0,
        "target_idle": 0,
        "is_train_only": True,
    },
}


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
    destination: str = "333",
    start: str = "odegaard",
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
    final_cfg = DESTINATION_OPTIONS.get(destination)
    if not final_cfg:
        return {"error": f"Unknown destination {destination}"}
    if start not in {"odegaard", "u_district_station"}:
        return {"error": f"Unknown start {start}"}

    line_label = "1 Line / 2 Line" if include_line2 else "1 Line"
    if start == "u_district_station":
        final_desc = final_cfg["station_label"] if final_cfg["is_train_only"] else final_cfg["label"]
        mode_description = f"U-District Station platform → {line_label} → {final_desc}"
    else:
        if final_cfg["is_train_only"]:
            if mode == 1:
                mode_description = f"{WALK_MODE1_TO_1LINE} min walk from Odegaard → U-District Station platform → {line_label} → {final_cfg['station_label']}"
            else:
                mode_description = f"Bus 44 / 372 from 15th Ave NE & NE Campus Pkwy, or Bus 45 from W Stevens Way NE → U-District Station → {line_label} → {final_cfg['station_label']}"
        else:
            mode_description = (
                cfg["description"]
                .replace("1 Line", line_label)
                .replace("Bus 333", final_cfg["label"])
            )

    # Latest acceptable departure from Odegaard based on stay window
    window_deadline = now + timedelta(minutes=stay_window)

    # Minimum time to physically catch the selected destination from the train
    min_buffer = final_cfg["transfer_walk"] + final_cfg["train_minutes"]

    results_in_window  = []  # connections within stay window
    results_outside    = []  # fallback: best connections outside window

    try:
        raw_arrivals = await get_arrivals(STOPS["u_district_station"], 120)
        trains_1line = by_route(raw_arrivals, ROUTES["1_line"])
        trains_2line = by_route(raw_arrivals, ROUTES["2_line"]) if include_line2 else []
        all_trains   = sorted(trains_1line + trains_2line, key=lambda t: depart_time(t))

        if final_cfg["is_train_only"]:
            final_bus_arrivals = [{"train_only": True}]
        else:
            final_bus_arrivals = by_route(await get_arrivals(final_cfg["stop_id"], 120), final_cfg["route_id"])
            if final_cfg["headsign"]:
                final_bus_arrivals = [
                    a for a in final_bus_arrivals
                    if final_cfg["headsign"].lower() in a.get("tripHeadsign", "").lower()
                ]

            if not final_bus_arrivals:
                return {"error": f"No {final_cfg['label']} departures found in the next 2 hours."}

        for last_bus in final_bus_arrivals:
            if final_cfg["is_train_only"]:
                last_bus_departs = None
                hard_latest_board = None
            else:
                last_bus_departs = depart_time(last_bus)
                # Hard limit: train must board early enough to physically reach the final destination
                hard_latest_board = last_bus_departs - timedelta(minutes=min_buffer)

            if start == "u_district_station":
                train = None
                best_score = None
                for t in all_trains:
                    t_departs = depart_time(t)
                    if t_departs < now - timedelta(minutes=1):
                        continue
                    if hard_latest_board and t_departs > hard_latest_board:
                        continue
                    t_arrive_shoreline = t_departs + timedelta(minutes=final_cfg["train_minutes"])
                    idle_secs = (last_bus_departs - t_arrive_shoreline).total_seconds() if last_bus_departs else 0
                    score = (idle_secs, t_departs.timestamp(), t_arrive_shoreline.timestamp())
                    if best_score is None or score < best_score:
                        best_score = score
                        train = t
                if not train:
                    continue

                train_departs = depart_time(train)
                arrive_shoreline = train_departs + timedelta(minutes=final_cfg["train_minutes"])
                total_mins_station = int(((last_bus_departs or arrive_shoreline) - train_departs).total_seconds() / 60)
                actual_idle_station = int(((last_bus_departs or arrive_shoreline) - arrive_shoreline).total_seconds() / 60)
                transfer_cushion_station = actual_idle_station - final_cfg["transfer_walk"]
                in_window_station = train_departs <= window_deadline
                entry = {
                    "leave_odegaard":  fmt(train_departs),
                    "minutes_until":   max(0, int((train_departs - now).total_seconds() / 60)),
                    "total_mins":      total_mins_station,
                    "transfer_wait_mins": actual_idle_station,
                    "transfer_cushion_mins": transfer_cushion_station,
                    "transfer_station_label": final_cfg["station_label"],
                    "transfer_walk_mins": final_cfg["transfer_walk"],
                    "walk_hint":       None,
                    "is_realtime":     train.get("predicted", False),
                    "mode":            1,
                    "start":           start,
                    "primary_action_label": "Board train",
                    "destination_label": final_cfg["label"] if not final_cfg["is_train_only"] else final_cfg["station_label"],
                    "steps": [
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
                if in_window_station:
                    results_in_window.append((actual_idle_station, entry))
                else:
                    results_outside.append((actual_idle_station, entry))

            elif mode == 1:
                train = None
                best_score = None
                for t in all_trains:
                    t_departs = depart_time(t)
                    if hard_latest_board and t_departs > hard_latest_board:
                        continue
                    t_arrive_shoreline = t_departs + timedelta(minutes=final_cfg["train_minutes"])
                    idle_secs = (last_bus_departs - t_arrive_shoreline).total_seconds() if last_bus_departs else 0
                    # Score: minimize wait at final station, tiebreak: earlier departure.
                    score = (idle_secs, t_departs.timestamp(), t_arrive_shoreline.timestamp())
                    if best_score is None or score < best_score:
                        best_score = score
                        train = t
                if not train:
                    continue

                train_departs = depart_time(train)
                arrive_shoreline = train_departs + timedelta(minutes=final_cfg["train_minutes"])
                leave = train_departs - timedelta(minutes=WALK_MODE1_TO_1LINE)
                if leave < now - timedelta(minutes=1):
                    continue
                total_mins_m1 = int((((last_bus_departs or arrive_shoreline)) - leave).total_seconds() / 60)
                actual_idle_m1 = int((((last_bus_departs or arrive_shoreline)) - arrive_shoreline).total_seconds() / 60)
                transfer_cushion_m1 = actual_idle_m1 - final_cfg["transfer_walk"]
                in_window_m1 = leave <= window_deadline
                entry = {
                    "leave_odegaard":  fmt(leave),
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
                    "primary_action_label": "Leave Odegaard",
                    "destination_label": final_cfg["label"] if not final_cfg["is_train_only"] else final_cfg["station_label"],
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
                if in_window_m1:
                    results_in_window.append((actual_idle_m1, entry))
                else:
                    results_outside.append((actual_idle_m1, entry))

            elif mode == 2:
                best_combo = None
                best_score = None
                for t in all_trains:
                    train_departs = depart_time(t)
                    if hard_latest_board and train_departs > hard_latest_board:
                        continue
                    arrive_shoreline = train_departs + timedelta(minutes=final_cfg["train_minutes"])
                    shoreline_wait_secs = (last_bus_departs - arrive_shoreline).total_seconds() if last_bus_departs else 0

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
                total_mins_m2 = int((((last_bus_departs or arrive_shoreline)) - leave).total_seconds() / 60)
                actual_idle_m2 = int((((last_bus_departs or arrive_shoreline)) - arrive_shoreline).total_seconds() / 60)
                transfer_cushion_m2 = actual_idle_m2 - final_cfg["transfer_walk"]
                in_window_m2 = leave <= window_deadline

                # Walk hint: if walking would let you leave closer to now with similar or less idle time
                walk_leave = train_departs - timedelta(minutes=WALK_MODE1_TO_1LINE)
                walk_mins_until = int((walk_leave - now).total_seconds() / 60)
                walk_hint = None
                if walk_mins_until >= -1:  # walk departure is still achievable
                    walk_idle = int((last_bus_departs - arrive_shoreline).total_seconds() / 60)
                    walk_hint = f"Walking now gives similar connection with {walk_idle} min at {final_cfg['station_label']}" if walk_mins_until <= 2 else None

                entry2 = {
                    "leave_odegaard": fmt(leave),
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
                    "primary_action_label": "Leave Odegaard",
                    "destination_label": final_cfg["label"] if not final_cfg["is_train_only"] else final_cfg["station_label"],
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
            out_of_window_note = f"No connections found within {stay_window} min departure window — showing nearest available"

    if not final:
        return {"error": "No viable connections found. Try refreshing."}

    return {
        "mode_description":   mode_description,
        "connections":        final,
        "out_of_window_note": out_of_window_note,
        "stay_window":        stay_window,
        "include_line2":      include_line2,
        "destination":        destination,
        "start":              start,
    }


@app.get("/api/connections")
async def get_connections(mode: int = 1, stay: int = 30, include_line2: bool = True, destination: str = "333", start: str = "odegaard"):
    return await find_connections(mode, stay_window=stay, include_line2=include_line2, destination=destination, start=start)

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
    final_walk_minutes = final_cfg["transfer_walk"]
    line_label = "1 Line / 2 Line" if include_line2 else "1 Line"
    final_leg_label = (
        f"Arrive {final_station}"
        if final_cfg["is_train_only"]
        else f"Walk {final_station} platform → {final_label} bay"
    )

    return {
        "mode1": [
            {"label": "Walk Odegaard → 1 Line platform (incl. buffer)", "min": WALK_MODE1_TO_1LINE,     "type": "walk"},
            {"label": f"{line_label} → {final_station}",                 "min": final_train_minutes, "type": "rail"},
            {"label": final_leg_label, "min": final_walk_minutes, "type": "end"},
        ],
        "bus_44_372": [
            {"label": "Walk Odegaard → stop (incl. buffer)", "min": WALK_TO_44_372,          "type": "walk"},
            {"label": "Bus 44/372 ride → Bay 1",             "min": RIDE_44_372_TO_UDIST,    "type": "bus"},
            {"label": "Walk Bay 1 → 1 Line platform",        "min": WALK_44_372_TO_1LINE,    "type": "walk2"},
            {"label": f"{line_label} → {final_station}",     "min": final_train_minutes, "type": "rail"},
            {"label": final_leg_label, "min": final_walk_minutes, "type": "end"},
        ],
        "bus_45": [
            {"label": "Walk Odegaard → stop (incl. buffer)", "min": WALK_TO_45,              "type": "walk"},
            {"label": "Bus 45 ride → Bay 5",                 "min": RIDE_45_TO_UDIST,        "type": "bus"},
            {"label": "Walk Bay 5 → 1 Line platform",        "min": WALK_45_TO_1LINE,        "type": "walk2"},
            {"label": f"{line_label} → {final_station}",     "min": final_train_minutes, "type": "rail"},
            {"label": final_leg_label, "min": final_walk_minutes, "type": "end"},
        ],
        "final_label": final_label,
        "final_station_label": final_station,
        "line_label": line_label,
        "is_train_only": final_cfg["is_train_only"],
    }

@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    with open("static/index.html") as f:
        return f.read()

if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
