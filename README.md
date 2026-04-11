# UW Commute Planner

A real-time commute assistant that tells you when to leave Odegaard Library to catch your connection home — built for my daily commute from UW to Shoreline.

**Live demo:** [uw-commute-planner.vercel.app](https://uw-commute-planner.vercel.app)

---

## What it does

Fetches live bus and train times from the [OneBusAway Puget Sound API](https://pugetsound.onebusaway.org) and works backwards from each upcoming Bus 333 departure to tell you the exact time to leave Odegaard Library, which bus or train to take, and whether the times are live or scheduled.

**Route:** Odegaard Library → U-District Station → 1 Line (light rail) → Shoreline South/148th → Bus 333

**Two modes:**
- **Walk** — 14 min walk from Odegaard to U-District Station
- **Bus** — Bus 44, 45, or 372 from stops near Odegaard to U-District Station

---

## Tech stack

- **Backend:** Python, FastAPI, httpx
- **Frontend:** Vanilla HTML / CSS / JavaScript
- **Data:** OneBusAway Puget Sound REST API (real-time + scheduled)
- **Hosting:** Vercel

---

## Run locally

```bash
# 1. Create and activate a conda environment
conda create -n commute-planner python=3.11
conda activate commute-planner

# 2. Install dependencies
pip install -r requirements.txt

# 3. Set your API key (optional — falls back to shared TEST key)
export OBA_API_KEY=your_key_here

# 4. Run
python app.py
```

Open `http://localhost:8000`

> **API key:** Request a free key by emailing `oba_api_key@soundtransit.org`. The app works without one using the shared `TEST` key, which may occasionally hit rate limits.

---

## Deploy to Vercel

1. Add a `vercel.json` to the project root:
```json
{
  "builds": [{ "src": "app.py", "use": "@vercel/python" }],
  "routes": [{ "src": "/(.*)", "dest": "app.py" }]
}
```

2. Push to GitHub, import the repo on [vercel.com](https://vercel.com)

3. Add `OBA_API_KEY` as an environment variable in the Vercel dashboard

4. Deploy — done

---

## Project structure

```
├── app.py              # FastAPI backend — algorithm + API calls
├── requirements.txt    # Python dependencies
├── vercel.json         # Vercel deployment config
└── static/
    └── index.html      # Frontend
```

---

## About

Built by **Alvin Alias** — MS Data Science student at the University of Washington (2025–2027). This started as a personal tool for my daily commute, and became a project to practice working with REST APIs and building full-stack apps.

[LinkedIn](https://www.linkedin.com/in/alvin-alias/) · [alvin.alias@gmail.com](mailto:alvin.alias@gmail.com)
