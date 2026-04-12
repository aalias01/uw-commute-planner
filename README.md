# UW Commute Planner

A real-time commute planner for one specific question: when should I leave — and from where — to catch the best connection home?

**Live demo:** [uw-commute-planner.vercel.app](https://uw-commute-planner.vercel.app)

---

## Why This Exists

General transit apps are great at showing routes, but they are not always great at answering a narrow, repeated decision:

**Should I leave now, wait a few minutes, walk straight to the station, or catch a feeder bus first? And where am I even starting from?**

This app is built around one real commute from UW. Instead of searching broadly, it works backwards from the selected destination and picks the best live option based on the current connection.

---

## What It Does

The planner pulls live arrivals from the [OneBusAway Puget Sound API](https://pugetsound.onebusaway.org) and evaluates your commute based on where you're starting and where you're headed.

**Two starting points:**

- **Odegaard Library:** full planning from campus. Choose Walk (direct to station) or Bus (feeder bus first).
- **U-District Station:** planning starts at the platform. Walk/Bus mode is skipped entirely.

**Three destinations:**

- **Bus 333:** Shoreline South/148th → Mountlake Terrace Station direction
- **Bus 348:** Shoreline North/185th → Richmond Beach direction
- **Train only:** ride ends at Shoreline North/185th with no final bus

The app is intentionally route-specific. It is designed for one commute and tries to make that commute feel effortless.

---

## How The Planner Decides

The planner works backwards from upcoming departures at the selected destination.

For each candidate trip, it:

1. Finds the latest train that can still physically make that destination.
2. For Walk mode (Odegaard start), calculates when you would need to leave Odegaard to catch that train.
3. For Bus mode (Odegaard start), checks Bus 44, 372, and 45 to find a feeder bus that still makes the train platform in time.
4. For U-District Station start, skips steps 2–3 entirely and goes straight to train selection.
5. For Train only destination, skips the final-bus lookup and ends the card at the train arrival.
6. Scores the result by:
   - least waiting at the final station
   - then least extra transfer wait earlier in the trip
   - then earlier departure when otherwise tied
7. Returns the best option plus one backup when available.

The result is not just “a route.” It is a recommendation for **what to do now**.

---

## Planner Vs Timings

The app has two views:

- **Planner:** live recommendations based on current departures
- **Timings:** baseline route assumptions from configured timing constants

That distinction matters:

- **Planner** includes live connection quality, transfer cushion, reliability labels, and fallback behavior when nothing fits your selected window.
- **Timings** shows physical route legs only. It does not include extra waiting caused by live schedules or missed connections.

---

## Current Features

- **Starting point selector:** begin planning from Odegaard Library or directly from U-District Station
- **Destination selector:** `333` (Mountlake Terrace), `348` (Richmond Beach), or `Train only` (Shoreline North)
- **Departure filter:** `Within N min` (show best options departing soon, with fallback) or `After N min` (show only options at or beyond a threshold)
- Live commute suggestions with fully manual refresh and visible report time
- `Leave within / Leave after` planner control with `15 / 30 / 45 / 60` minute options
- Walk and Bus commute modes (Odegaard start only)
- Include Line 2 toggle in Planner
- Saved default setup for favorite planner settings
- Best option + backup option presentation
- Realtime vs scheduled badges
- Transfer cushion messaging with reliability labels:
  - `Tight`
  - `Okay`
  - `Comfortable`
- Step-by-step Depart / Arrive breakdown for each option as a visual timeline
- Fallback suggestions when nothing fits inside a `Within` window
- Local browser snapshots with 24-hour expiry
- Timings page driven by backend timing constants with destination-specific display toggle
- Direction filtering for buses and Bus 45 dropoff validation

---

## Current Route Assumptions

The planner is built around this commute shape:

- **Starting point:** Odegaard Library or U-District Station
- **U-District Station** (1 Line / 2 Line platform)
- **Shoreline South/148th** for `333`, **Shoreline North/185th** for `348` and `Train only`
- Final bus home (or ride ends at the train station for `Train only`)

Important route-specific behavior:

- `333` is filtered to the **Mountlake Terrace Station** direction from Shoreline South Bay 2.
- `348` is filtered to the **Richmond Beach** direction from Shoreline North Bay 3.
- Bus direction filtering matters for `44`, `45`, and `372`.
- Bus `45` trips are additionally checked to make sure they really serve the intended U-District dropoff stop.
- When starting at **U-District Station**, all feeder-bus logic and walk-time calculations are skipped.

---

## Tech Stack

- **Backend:** Python, FastAPI, httpx, uvicorn
- **Frontend:** Vanilla HTML / CSS / JavaScript
- **Data:** OneBusAway Puget Sound REST API
- **Hosting:** Vercel

---

## Run Locally

```bash
conda create -n commute-planner python=3.11
conda activate commute-planner
pip install -r requirements.txt
export OBA_API_KEY=your_key_here  # optional
python app.py
```

Open [http://localhost:8000](http://localhost:8000).

If `OBA_API_KEY` is not set, the app falls back to the shared `TEST` key. That works, but it can hit rate limits occasionally.

---

## API Endpoints

- `GET /` serves the frontend
- `GET /api/connections?mode=1&stay=30&window_mode=within&include_line2=true&destination=333&start=odegaard` returns live planner suggestions
- `GET /api/modes` returns available planner modes
- `GET /api/timings?destination=333&include_line2=true` returns the timing data used by the Timings page

Key `/api/connections` parameters:

| Parameter | Values | Default |
|-----------|--------|---------|
| `mode` | `1` (Walk), `2` (Bus) | `1` |
| `stay` | `15`, `30`, `45`, `60` | `30` |
| `window_mode` | `within`, `after` | `within` |
| `include_line2` | `true`, `false` | `true` |
| `destination` | `333`, `348`, `train_north` | `333` |
| `start` | `odegaard`, `u_district_station` | `odegaard` |

---

## Project Structure

```text
commute-planner/
├── app.py
├── requirements.txt
├── vercel.json
├── README.md
├── static/
│   ├── html2canvas.min.js
│   └── index.html
└── docs_local/
    ├── CONTEXT.md
    └── CHANGELOG.md
```

---

## Deployment

Deploys cleanly on Vercel.

1. Push the repo to GitHub.
2. Import the repo into Vercel.
3. Set `OBA_API_KEY` in the Vercel environment settings.
4. Deploy.

The repo already includes `vercel.json`.

---

## Notes

- This is intentionally a personal, route-specific planner rather than a generic trip planner.
- Line 2 support is controlled from the Planner UI and defaults to on.
- Planner results only change when you press `Refresh`.
- Timing assumptions live near the top of `app.py`.
- The Timings page reflects configured assumptions; the Planner reflects live conditions.
- `Within` mode falls back to the nearest available option if nothing fits the selected window. `After` mode returns an error with no fallback.
- All saved defaults (including starting point, destination, and departure filter) are persisted to `localStorage`.

---

## About

Built by **Alvin Alias** as a personal full-stack project around a daily UW commute.

[LinkedIn](https://www.linkedin.com/in/alvin-alias/) · [alvin.alias@gmail.com](mailto:alvin.alias@gmail.com)
