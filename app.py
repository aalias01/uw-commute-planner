from fastapi import FastAPI
from fastapi.responses import HTMLResponse
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
    "2_line":  "40_2LINE",   # Sound Transit 2 Line (re-enable when construction ends)
    "bus_333": "1_102746",
    "bus_44":  "1_100224",
    "bus_45":  "1_100225",
    "bus_372": "1_100214",
}

# ─── TIMING SETTINGS ─────────────────────────────────────────────────────────
# All values in minutes. These are the only values you need to update
# if your walk times or route timings change.

# Mode 1: walk from Odegaard to U-District Station
WALK_ODEGAARD_TO_UDIST  = 14

# Mode 2: walk from Odegaard to each bus stop
WALK_TO_44_372          = 4    # 15th Ave NE & NE Campus Pkwy
WALK_TO_45              = 7    # W Stevens Way NE & George Washington Ln

# Mode 2: ride time from each bus stop to U-District Station
RIDE_44_372_TO_UDIST    = 5
RIDE_45_TO_UDIST        = 4

# Mode 2: arrive at stop this many mins before bus departs
BUFFER_44_372           = 3
BUFFER_45               = 5

# 1 Line: travel time U-District Station → Shoreline South/148th
LIGHT_RAIL_TO_SHORELINE = 12

# Minimum mins to arrive at Shoreline South before Bus 333 departs
BUFFER_BEFORE_333       = 5

# Mins needed at U-District Station before boarding 1 Line
WAIT_AT_UDIST           = 2
# ──────────────────────────────────────────────────────────────────────────────

# Bus stops near Odegaard for Mode 2
BUS_OPTIONS = {
    "bus_44": {
        "label":         "Bus 44",
        "stop_id":       "1_10914",
        "stop_name":     "15th Ave NE & NE Campus Pkwy",
        "route_id":      "1_100224",
        "walk_to_stop":  WALK_TO_44_372,
        "ride_to_udist": RIDE_44_372_TO_UDIST,
        "buffer":        BUFFER_44_372,
    },
    "bus_372": {
        "label":         "Bus 372",
        "stop_id":       "1_10914",
        "stop_name":     "15th Ave NE & NE Campus Pkwy",
        "route_id":      "1_100214",
        "walk_to_stop":  WALK_TO_44_372,
        "ride_to_udist": RIDE_44_372_TO_UDIST,
        "buffer":        BUFFER_44_372,
    },
    "bus_45": {
        "label":         "Bus 45",
        "stop_id":       "1_75405",
        "stop_name":     "W Stevens Way NE & George Washington Ln",
        "route_id":      "1_100225",
        "walk_to_stop":  WALK_TO_45,
        "ride_to_udist": RIDE_45_TO_UDIST,
        "buffer":        BUFFER_45,
    },
}

MODES = {
    1: {
        "name":        "Walk",
        "description": f"{WALK_ODEGAARD_TO_UDIST} min walk from Odegaard → U-District Station → 1 Line → Bus 333",
        "bus_options": [],
        "use_2_line":  False,  # set True when Line 2 construction ends
    },
    2: {
        "name":        "Bus",
        "description": "Bus 44 / 45 / 372 from near Odegaard → U-District Station → 1 Line → Bus 333",
        "bus_options": ["bus_44", "bus_372", "bus_45"],
        "use_2_line":  False,
    },
}

app = FastAPI(title="UW Commute Planner")


async def get_arrivals(stop_id: str, minutes_after: int = 90) -> list:
    url    = f"{OBA_BASE}/arrivals-and-departures-for-stop/{stop_id}.json"
    params = {"key": API_KEY, "minutesAfter": minutes_after, "minutesBefore": 0}
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
    return resp.json().get("data", {}).get("entry", {}).get("arrivalsAndDepartures", [])


def by_route(arrivals: list, route_id: str) -> list:
    return [a for a in arrivals if a.get("routeId") == route_id]


def depart_time(a: dict) -> datetime:
    predicted = a.get("predictedDepartureTime", 0)
    scheduled = a.get("scheduledDepartureTime", 0)
    ts = predicted if predicted > 0 else scheduled
    return datetime.fromtimestamp(ts / 1000, tz=SEATTLE)


def fmt(dt: datetime) -> str:
    return dt.strftime("%I:%M %p")


async def best_bus(bus_key: str, must_arrive_udist_by: datetime) -> Optional[dict]:
    cfg      = BUS_OPTIONS[bus_key]
    arrivals = by_route(await get_arrivals(cfg["stop_id"]), cfg["route_id"])

    pick = None
    for a in arrivals:
        d = depart_time(a)
        if d + timedelta(minutes=cfg["ride_to_udist"]) <= must_arrive_udist_by:
            pick = a

    if not pick:
        return None

    d = depart_time(pick)
    return {
        "label":         cfg["label"],
        "stop_name":     cfg["stop_name"],
        "walk_to_stop":  cfg["walk_to_stop"],
        "buffer":        cfg["buffer"],
        "leave_odegaard":d - timedelta(minutes=cfg["walk_to_stop"] + cfg["buffer"]),
        "bus_departs":   d,
        "arrive_udist":  d + timedelta(minutes=cfg["ride_to_udist"]),
        "is_realtime":   pick.get("predicted", False),
    }


async def find_connections(mode: int, now: Optional[datetime] = None) -> dict:
    if now is None:
        now = datetime.now(SEATTLE)

    cfg = MODES.get(mode)
    if not cfg:
        return {"error": f"Unknown mode {mode}"}

    results = []

    try:
        buses_333   = by_route(await get_arrivals(STOPS["shoreline_south_bay1"], 120), ROUTES["bus_333"])
        trains_1line = by_route(await get_arrivals(STOPS["u_district_station"],   120), ROUTES["1_line"])

        if not buses_333:
            return {"error": "No Bus 333 departures found in the next 2 hours."}

        for b333 in buses_333:
            b333_departs = depart_time(b333)

            latest_arrive_shoreline = b333_departs    - timedelta(minutes=BUFFER_BEFORE_333)
            latest_board_1line      = latest_arrive_shoreline - timedelta(minutes=LIGHT_RAIL_TO_SHORELINE)
            latest_arrive_udist     = latest_board_1line      - timedelta(minutes=WAIT_AT_UDIST)

            # Find the latest 1 Line train that still boards in time
            train = None
            for t in trains_1line:
                if depart_time(t) <= latest_board_1line:
                    train = t
            if not train:
                continue

            train_departs    = depart_time(train)
            arrive_udist     = train_departs - timedelta(minutes=WAIT_AT_UDIST)
            arrive_shoreline = train_departs + timedelta(minutes=LIGHT_RAIL_TO_SHORELINE)

            if mode == 1:
                leave = arrive_udist - timedelta(minutes=WALK_ODEGAARD_TO_UDIST)
                if leave < now - timedelta(minutes=1):
                    continue
                results.append({
                    "leave_odegaard":  fmt(leave),
                    "minutes_until":   max(0, int((leave - now).total_seconds() / 60)),
                    "is_realtime":     train.get("predicted", False),
                    "mode":            1,
                    "steps": [
                        {"icon": "walk", "label": "Walk to U-District Station",
                         "depart": fmt(leave), "arrive": fmt(arrive_udist),
                         "wait_after": int((train_departs - arrive_udist).total_seconds() / 60)},
                        {"icon": "rail", "label": "1 Line → Lynnwood",
                         "depart": fmt(train_departs), "arrive": fmt(arrive_shoreline),
                         "wait_after": int((b333_departs - arrive_shoreline).total_seconds() / 60)},
                        {"icon": "bus",  "label": "Bus 333 → Home",
                         "depart": fmt(b333_departs), "arrive": None,
                         "wait_after": None},
                    ]
                })

            elif mode == 2:
                pick = None
                for bk in cfg["bus_options"]:
                    r = await best_bus(bk, arrive_udist)
                    if r is None:
                        continue
                    if r["leave_odegaard"] < now - timedelta(minutes=1):
                        continue
                    if pick is None or r["leave_odegaard"] > pick["leave_odegaard"]:
                        pick = r
                if not pick:
                    continue

                leave = pick["leave_odegaard"]
                results.append({
                    "leave_odegaard": fmt(leave),
                    "minutes_until":  max(0, int((leave - now).total_seconds() / 60)),
                    "is_realtime":    pick["is_realtime"] or train.get("predicted", False),
                    "mode":           2,
                    "steps": [
                        {"icon": "bus",  "label": f"{pick['label']} from {pick['stop_name']}",
                         "depart": fmt(pick["bus_departs"]), "arrive": fmt(pick["arrive_udist"]),
                         "wait_after": int((train_departs - pick["arrive_udist"]).total_seconds() / 60)},
                        {"icon": "rail", "label": "1 Line → Lynnwood",
                         "depart": fmt(train_departs),       "arrive": fmt(arrive_shoreline),
                         "wait_after": int((b333_departs - arrive_shoreline).total_seconds() / 60)},
                        {"icon": "bus",  "label": "Bus 333 → Home",
                         "depart": fmt(b333_departs),        "arrive": None},
                    ]
                })

            if len(results) >= 4:
                break

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 429:
            return {"error": "rate_limit"}
        return {"error": f"API error: {e.response.status_code}"}
    except httpx.HTTPError as e:
        return {"error": f"Network error: {str(e)}"}

    if not results:
        return {"error": "No viable connections found. Try refreshing."}

    return {
        "mode_description": cfg["description"],
        "connections":      results,
    }


@app.get("/api/connections")
async def get_connections(mode: int = 1):
    return await find_connections(mode)

@app.get("/api/modes")
async def get_modes():
    return {"modes": [{"id": k, "name": v["name"], "description": v["description"]} for k, v in MODES.items()]}

@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    with open("static/index.html") as f:
        return f.read()

if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
