# Watchlist App v2 — Flask + PostgreSQL

Multi-user watchlist with profiles, authentication, and OMDB data.

## Features
- Register / login with username + password
- Multiple profiles per account (e.g. Kids, Partner, Work)
- Each profile has its own independent watchlist
- OMDB data: ratings, genres, runtime, poster, description
- Card view and list view
- Multi-select and bulk delete
- All data stored in PostgreSQL (persists across sessions)

---

## Step 1 — Get a free OMDB API key
Go to https://www.omdbapi.com/apikey.aspx → FREE tier → activate via email.

---

## Step 2 — Set up PostgreSQL on Render (free)

1. Go to https://render.com → New → PostgreSQL
2. Name it `watchlist-db`, choose Free tier
3. Click Create — wait ~1 min
4. Copy the **Internal Database URL** (used within Render)
   or the **External Database URL** (for local dev)

---

## Step 3 — Push to GitHub

```bash
git init
git add .
git commit -m "initial commit"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/watchlist.git
git push -u origin main
```

---

## Step 4 — Deploy Web Service on Render

1. New → Web Service → connect your GitHub repo
2. Settings:
   - Runtime: Python 3
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `gunicorn app:app`
   - Instance Type: Free
3. Environment Variables (click Advanced → Add Env Var):
   - `DATABASE_URL` → paste the Internal Database URL from Step 2
   - `OMDB_API_KEY` → your OMDB key
   - `SECRET_KEY` → any random string, e.g. `mysecretkey123abc`
4. Create Web Service → live in ~2 min

---

## Running locally

```bash
pip install -r requirements.txt

# Set env vars (Mac/Linux)
export DATABASE_URL=postgresql://user:pass@localhost/watchlist
export OMDB_API_KEY=your_key
export SECRET_KEY=any_random_string

# Or use a .env file (python-dotenv is included)
# Create .env:
# DATABASE_URL=...
# OMDB_API_KEY=...
# SECRET_KEY=...

python app.py
# Visit http://localhost:5000
```

For local PostgreSQL, create the DB first:
```bash
createdb watchlist
```

SQLite also works for local dev — just omit DATABASE_URL and it'll use a local file.

---

## File structure
```
watchlist2/
├── app.py                  # Flask backend (auth, profiles, entries, OMDB proxy)
├── requirements.txt
├── README.md
└── static/
    ├── auth.html           # Login / register page
    └── index.html          # Main watchlist app (served at /app)
```

## Notes
- Passwords are hashed with bcrypt — never stored in plain text
- Sessions use Flask-Login with a secure cookie
- The free Render PostgreSQL instance persists data (unlike the free web service which resets)
- Render free web service sleeps after 15 min inactivity — first visit may take ~30s to wake
