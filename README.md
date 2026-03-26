# Watchlist App

A personal movie & TV tracker powered by Flask + Anthropic API.

## Setup

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Set your Anthropic API key
```bash
# Mac/Linux
export ANTHROPIC_API_KEY=sk-ant-...

# Windows
set ANTHROPIC_API_KEY=sk-ant-...
```

Get your API key at: https://console.anthropic.com

### 3. Run locally
```bash
python app.py
```
Open http://localhost:5000 in your browser.

---

## Deploying to a server (e.g. DigitalOcean, Render, Railway)

### Option A — Gunicorn (production WSGI server)
```bash
pip install gunicorn
gunicorn app:app --bind 0.0.0.0:5000
```

### Option B — Render.com (free tier)
1. Push this folder to a GitHub repo
2. Create a new **Web Service** on Render
3. Set **Build Command**: `pip install -r requirements.txt`
4. Set **Start Command**: `gunicorn app:app`
5. Add environment variable: `ANTHROPIC_API_KEY` = your key
6. Deploy — Render gives you a public URL automatically

### Option C — Railway.app
1. Push to GitHub, connect repo on Railway
2. Add `ANTHROPIC_API_KEY` in Variables tab
3. Railway auto-detects Python and deploys

---

## File structure
```
watchlist/
├── app.py              # Flask backend (API proxy)
├── requirements.txt    # Python dependencies
├── README.md
└── static/
    └── index.html      # Full frontend
```

## How it works
- The frontend (`index.html`) calls `/api/fetch-info` on your Flask server
- Flask adds your API key and forwards the request to Anthropic
- Info is cached in the browser's localStorage so it only fetches once
- Watched/pending status is also saved in localStorage
