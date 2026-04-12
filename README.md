# UW Commute Planner

A real-time commute planner built around one question: when should I leave, and from where, to catch the best connection home?

**Live demo:** [uw-commute-planner.vercel.app](https://uw-commute-planner.vercel.app)

---

## Why This Exists

General transit apps are great at showing routes, but rarely answer a narrow, repeated decision well:

> Should I leave now or wait — and which option minimizes my time standing around at a transfer?

This app is built around one real commute from UW. Instead of searching broadly, it works backwards from the destination and finds the best live option for the current moment.

---

## What It Does

The planner pulls live arrivals from the [OneBusAway Puget Sound API](https://pugetsound.onebusaway.org) and recommends when to leave based on your starting point and destination.

**Two starting points:**

- **Odegaard Library** — full planning from campus with Walk or Bus mode
- **U-District Station** — planning starts at the platform; feeder bus logic is skipped entirely

**Three destinations:**

- **Bus 333** — Shoreline South/148th toward Mountlake Terrace Station
- **Bus 348** — Shoreline North/185th toward Richmond Beach
- **Train only** — ride ends at Shoreline North/185th with no final bus

---

## How The Planner Decides

For each candidate trip, the planner works backwards from the destination:

1. Finds the latest train that can physically make that destination.
2. For **Walk mode**, calculates when you need to leave Odegaard to catch that train.
3. For **Bus mode**, checks Bus 44, 372, and 45 for a feeder that still makes the platform in time.
4. For **U-District Station start**, skips steps 2–3 and goes straight to train selection.
5. Scores results by least wait at the final station, then least extra transfer wait, then earliest departure when tied.
6. Returns up to three cards: Best option, Backup option, and Earliest departure.

The result is not just a route — it's a recommendation for **what to do right now**.

---

## Planner vs Timings

The app has two views:

- **Planner** — live recommendations based on current departures, with transfer buffer, reliability labels, and fallback behavior
- **Timings** — static route leg breakdown driven by timing constants in `app.py`, with no live data

---

## Features

- Starting point selector: Odegaard Library or U-District Station
- Destination selector: Bus 333, Bus 348, or Train only
- Departure filter: `Within N min` (with fallback) or `After N min` (strict, no fallback)
- Walk and Bus commute modes (Odegaard start only)
- Leave window: 15 / 30 min presets or a custom value (1–240 min)
- Include Line 2 toggle
- Transfer buffer with reliability labels: Tight / Okay / Comfortable
- Up to three result cards: Best option, Backup option, and Earliest departure
- Step-by-step visual timeline on each card with live vs scheduled badge
- Saved defaults persisted to localStorage
- Manual refresh with visible report time
- Local browser snapshots with 24-hour expiry (up to 6 saved)
- Timings page with destination-specific display toggle
- Direction filtering for all feeder buses and Bus 45 dropoff validation

---

## Route Assumptions

The planner is built around this commute shape:

- **Odegaard Library** or **U-District Station** → train platform
- **1 Line / 2 Line** toward Shoreline
- **Shoreline South/148th** (Bus 333) or **Shoreline North/185th** (Bus 348 / Train only)
- Final bus home, or ride ends at the train station for Train only

Route-specific details:

- Bus 333 is filtered to the Mountlake Terrace Station direction from Shoreline South Bay 2.
- Bus 348 is filtered to the Richmond Beach direction from Shoreline North Bay 3.
- Bus 45 trips are validated to confirm they serve the intended U-District dropoff stop.

---

## Tech Stack

| Layer | Tools |
|-------|-------|
| Backend | Python, FastAPI, httpx, uvicorn |
| Frontend | Vanilla HTML / CSS / JavaScript |
| Data | OneBusAway Puget Sound REST API |
| Hosting | Vercel |

---

## Run Locally

```bash
conda create -n commute-planner python=3.11
conda activate commute-planner
pip install -r requirements.txt
export OBA_API_KEY=your_key_here  # optional, falls back to shared TEST key
python app.py
```

Open [http://localhost:8000](http://localhost:8000).

> **API key:** The app works without one using the shared `TEST` key, but for reliable use you can request a free key via [Sound Transit's Open Transit Data portal](https://www.soundtransit.org/help-contacts/business-information/open-transit-data-otd).

---

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /` | Serves the frontend |
| `GET /api/connections` | Returns live planner suggestions |
| `GET /api/timings` | Returns timing data for the Timings page |
| `GET /api/modes` | Returns available commute modes |

**`/api/connections` parameters:**

| Parameter | Values | Default |
|-----------|--------|---------|
| `mode` | `1` Walk, `2` Bus | `2` |
| `stay` | any integer from `1` to `240` | `30` |
| `window_mode` | `within` `after` | `within` |
| `include_line2` | `true` `false` | `true` |
| `destination` | `333` `348` `train_north` | `333` |
| `start` | `odegaard` `u_district_station` | `odegaard` |

---

## Project Structure

```text
commute-planner/
├── app.py
├── requirements.txt
├── vercel.json
├── README.md
├── static/
│   ├── index.html
│   └── html2canvas.min.js
└── docs_local/
    ├── CONTEXT.md
    └── CHANGELOG.md
```

---

## Deploy to Vercel

1. Push to GitHub.
2. Import the repo in Vercel.
3. Add `OBA_API_KEY` under Environment Variables.
4. Deploy — `vercel.json` is already configured.

---

## About

Built by **Alvin Alias** as a personal full-stack project around a real daily commute.

[LinkedIn](https://www.linkedin.com/in/alvin-alias/) · [learnalvin@gmail.com](mailto:learnalvin@gmail.com)
