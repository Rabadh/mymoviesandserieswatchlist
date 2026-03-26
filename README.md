# My Watchlist

A personal movie & TV tracker using the free OMDB API for real IMDb data, hosted on Render.

## Everything is free
- **OMDB API** — 1,000 requests/day free. No credit card needed.
- **GitHub** — free repo
- **Render.com** — free web service tier

---

## Step 1 — Get a free OMDB API key

1. Go to https://www.omdbapi.com/apikey.aspx
2. Choose **FREE** (1,000 daily limit)
3. Enter your email and submit
4. Check your email and click the activation link
5. Save your API key (looks like: `a1b2c3d4`)

---

## Step 2 — Push to GitHub

1. Create a new repo on https://github.com/new
   - Name it `watchlist` (or anything you like)
   - Set it to **Public** or **Private** — both work with Render free tier
   - Do NOT add a README (you already have files)

2. In your terminal, inside this folder:
```bash
git init
git add .
git commit -m "initial commit"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
git push -u origin main
```

---

## Step 3 — Deploy on Render (free)

1. Go to https://render.com and sign up (free)
2. Click **New** → **Web Service**
3. Connect your GitHub account and select your repo
4. Fill in the settings:
   - **Name**: watchlist (or anything)
   - **Runtime**: Python 3
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn app:app`
   - **Instance Type**: Free
5. Click **Advanced** → **Add Environment Variable**
   - Key: `OMDB_API_KEY`
   - Value: your key from Step 1
6. Click **Create Web Service**

Render will build and deploy. In ~2 minutes you'll get a live URL like:
`https://watchlist-xxxx.onrender.com`

---

## Running locally (optional)

```bash
pip install -r requirements.txt
export OMDB_API_KEY=your_key_here   # Mac/Linux
# set OMDB_API_KEY=your_key_here    # Windows

python app.py
# open http://localhost:5000
```

---

## File structure

```
watchlist/
├── app.py              # Flask backend — proxies OMDB API calls
├── requirements.txt    # Python dependencies (includes gunicorn)
├── README.md
└── static/
    └── index.html      # Full frontend (HTML/CSS/JS)
```

## Notes
- Info and watched status are saved in your browser's localStorage
- "Reload info" button re-fetches everything fresh from OMDB
- OMDB free tier: 1,000 requests/day. With 80 titles that's fine for personal use.
- Render free tier spins down after 15 min of inactivity — first load may take ~30 seconds to wake up
