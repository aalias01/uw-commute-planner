# UW Commute Planner

A real-time commute planner for one specific question: when should I leave Odegaard right now to catch the best connection home?

**Live demo:** [uw-commute-planner.vercel.app](https://uw-commute-planner.vercel.app)

---

## Why This Exists

General transit apps are great at showing routes, but they are not always great at answering a narrow, repeated decision:

**Should I leave now, wait a few minutes, walk straight to the station, or catch a feeder bus first?**

This app is built around one real commute from UW. Instead of searching broadly, it works backwards from the final bus and picks the best live option based on the current connection.

---

## What It Does

The planner pulls live arrivals from the [OneBusAway Puget Sound API](https://pugetsound.onebusaway.org) and evaluates two commute modes:

- **Walk:** Odegaard → U-District Station platform → train → final bus
- **Bus:** feeder bus → U-District Station → train → final bus

It currently supports two final-bus branches:

- **Bus 333:** Shoreline South/148th → Mountlake Terrace Station direction
- **Bus 348:** Shoreline North/185th → Richmond Beach direction

The app is intentionally route-specific. It is designed for one commute and tries to make that commute feel effortless.

---

## How The Planner Decides

The planner works backwards from upcoming departures of the selected final bus.

For each candidate final-bus trip, it:

1. Finds the latest train that can still physically make that bus.
2. For Walk mode, calculates when you would need to leave Odegaard to catch that train.
3. For Bus mode, checks Bus 44, 372, and 45 to find a feeder bus that still makes the train platform in time.
4. Scores the result by:
   - least waiting at the final station
   - then least extra transfer wait earlier in the trip
   - then earlier departure when otherwise tied
5. Returns the best option plus one backup when available.

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

- Live commute suggestions based on the selected final bus branch (`333` or `348`)
- Fully manual refresh with visible report time
- `Leave within` planner control with `15 / 30 / 45 / 60` minute options
- Walk and Bus commute modes
- Final-bus selector in Planner
- Separate final-bus display toggle in Timings
- Include Line 2 toggle in Planner
- Saved default setup for favorite planner settings
- Best option + backup option presentation
- Realtime vs scheduled badges
- Transfer cushion messaging with reliability labels:
  - `Tight`
  - `Okay`
  - `Comfortable`
- Step-by-step Depart / Arrive breakdown for each option
- Fallback suggestions when nothing fits inside the selected window
- Local browser snapshots with 24-hour expiry
- Timings page driven by backend timing constants
- Direction filtering for buses and Bus 45 dropoff validation

---

## Current Route Assumptions

The planner is built around this commute shape:

- **Odegaard Library**
- **U-District Station**
- **1 Line / 2 Line**
- **Shoreline South/148th** for `333` or **Shoreline North/185th** for `348`
- final bus home

Important route-specific behavior:

- `333` is filtered to the **Mountlake Terrace Station** direction.
- `348` is filtered to the **Richmond Beach** direction.
- Bus direction filtering matters for `44`, `45`, and `372`.
- Bus `45` trips are additionally checked to make sure they really serve the intended U-District dropoff stop.

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
- `GET /api/connections?mode=1&stay=30&include_line2=true&final_bus=333` returns live planner suggestions
- `GET /api/modes` returns available planner modes
- `GET /api/timings?final_bus=333&include_line2=true` returns the timing data used by the Timings page

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

---

## About

Built by **Alvin Alias** as a personal full-stack project around a daily UW commute.

[LinkedIn](https://www.linkedin.com/in/alvin-alias/) · [alvin.alias@gmail.com](mailto:alvin.alias@gmail.com)
