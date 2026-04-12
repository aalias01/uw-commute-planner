# UW Commute Planner

A real-time commute planner that tells you when to leave Odegaard Library to catch the best connection home.

**Live demo:** [uw-commute-planner.vercel.app](https://uw-commute-planner.vercel.app)

---

## What It Does

The app fetches live bus and train times from the [OneBusAway Puget Sound API](https://pugetsound.onebusaway.org) and works backwards from the selected final bus departure.

It helps answer one simple question: **when should I leave Odegaard right now?**

Current route branches:

- **Odegaard Library → U-District Station → 1 Line / 2 Line → Shoreline South/148th → Bus 333**
- **Odegaard Library → U-District Station → 1 Line / 2 Line → Shoreline North/185th → Bus 348**

The app currently supports two commute modes:

- **Walk**: walk from Odegaard directly to the U-District Station platform
- **Bus**: take Bus 44, 372, or 45 to U-District Station, then transfer to the train

---

## Current Features

- Live commute suggestions based on the selected final bus branch (`333` or `348`)
- Manual refresh with visible report time
- `Leave within` planning with `15 / 30 / 45 / 60` minute options
- Walk and Bus commute modes
- Final-bus selector in Planner (`333` / `348`)
- Separate final-bus display toggle in Timings
- Include Line 2 toggle in Planner
- Saved default setup for preferred planner choices
- Realtime vs scheduled badges on each connection card
- Best option + backup option presentation
- Transfer cushion messaging with reliability labels (`Tight`, `Okay`, `Comfortable`)
- Step-by-step Depart / Arrive breakdown for every connection
- Fallback suggestions when nothing fits inside the selected stay window
- Local snapshot saving in the browser with 24-hour expiry
- Timings page driven by backend timing constants
- Timings page reflects `1 Line / 2 Line` display and the selected final-bus branch
- Direction filtering for buses plus Bus 45 dropoff validation

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

> The app falls back to the shared `TEST` key if `OBA_API_KEY` is not set. That works, but it can occasionally hit rate limits.

---

## API Endpoints

- `GET /` serves the frontend
- `GET /api/connections?mode=1&stay=30&include_line2=true&final_bus=333` returns current route suggestions
- `GET /api/modes` returns the available planner modes
- `GET /api/timings?final_bus=333&include_line2=true` returns the timing values used by the Timings page

---

## Project Structure

```text
commute-planner/
├── app.py
├── requirements.txt
├── vercel.json
├── README.md
├── static/
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

- The app is built around one personal commute, so the routing logic is intentionally specific rather than generic.
- Line 2 support is controlled from the Planner UI and defaults to on.
- Planner results only change when you press `Refresh`.
- Direction filtering for buses matters a lot because OneBusAway returns both directions at the same stop.

---

## About

Built by **Alvin Alias** as a personal full-stack project around a daily UW commute.

[LinkedIn](https://www.linkedin.com/in/alvin-alias/) · [alvin.alias@gmail.com](mailto:alvin.alias@gmail.com)
