import os
import requests
from flask import Flask, request, jsonify, send_from_directory, session
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_cors import CORS
from datetime import datetime

app = Flask(__name__, static_folder="static", template_folder="templates")
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-in-prod")
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///watchlist.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
# Fix for Render's postgres:// vs postgresql://
if app.config["SQLALCHEMY_DATABASE_URI"].startswith("postgres://"):
    app.config["SQLALCHEMY_DATABASE_URI"] = app.config["SQLALCHEMY_DATABASE_URI"].replace("postgres://", "postgresql://", 1)

CORS(app, supports_credentials=True)
db = SQLAlchemy(app)
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)

OMDB_API_KEY = os.environ.get("OMDB_API_KEY", "")

# ── Models ──────────────────────────────────────────────────────────────

class User(UserMixin, db.Model):
    __tablename__ = "users"
    id       = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    profiles = db.relationship("Profile", backref="user", cascade="all, delete-orphan")
    created  = db.Column(db.DateTime, default=datetime.utcnow)

class Profile(db.Model):
    __tablename__ = "profiles"
    id      = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    name    = db.Column(db.String(80), nullable=False)
    entries = db.relationship("Entry", backref="profile", cascade="all, delete-orphan")
    created = db.Column(db.DateTime, default=datetime.utcnow)

class Entry(db.Model):
    __tablename__ = "entries"
    id          = db.Column(db.Integer, primary_key=True)
    profile_id  = db.Column(db.Integer, db.ForeignKey("profiles.id"), nullable=False)
    title       = db.Column(db.String(200), nullable=False)
    watched     = db.Column(db.Boolean, default=False)
    media_type  = db.Column(db.String(30))
    genres      = db.Column(db.String(200))
    runtime     = db.Column(db.String(50))
    rating      = db.Column(db.Float)
    year        = db.Column(db.String(10))
    poster      = db.Column(db.String(500))
    plot        = db.Column(db.Text)
    custom_desc = db.Column(db.Text)
    added       = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id":          self.id,
            "title":       self.title,
            "watched":     self.watched,
            "type":        self.media_type,
            "genres":      self.genres.split(",") if self.genres else [],
            "runtime":     self.runtime,
            "rating":      self.rating,
            "year":        self.year,
            "poster":      self.poster or "",
            "plot":        self.plot or "",
            "custom_desc": self.custom_desc or "",
        }

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@login_manager.unauthorized_handler
def unauthorized():
    return jsonify({"error": "Unauthorized"}), 401

# ── Auth routes ──────────────────────────────────────────────────────────

@app.route("/api/register", methods=["POST"])
def register():
    data = request.get_json()
    username = (data.get("username") or "").strip().lower()
    password = data.get("password", "")
    if not username or not password:
        return jsonify({"error": "Username and password required"}), 400
    if len(username) < 3:
        return jsonify({"error": "Username must be at least 3 characters"}), 400
    if len(password) < 4:
        return jsonify({"error": "Password must be at least 4 characters"}), 400
    if User.query.filter_by(username=username).first():
        return jsonify({"error": "Username already taken"}), 409
    hashed = bcrypt.generate_password_hash(password).decode("utf-8")
    user = User(username=username, password=hashed)
    db.session.add(user)
    db.session.flush()
    # Create a default profile
    default_profile = Profile(user_id=user.id, name=username.capitalize() + "'s List")
    db.session.add(default_profile)
    db.session.commit()
    login_user(user)
    return jsonify({"ok": True, "username": user.username, "profiles": [{"id": default_profile.id, "name": default_profile.name}]})

@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json()
    username = (data.get("username") or "").strip().lower()
    password = data.get("password", "")
    user = User.query.filter_by(username=username).first()
    if not user or not bcrypt.check_password_hash(user.password, password):
        return jsonify({"error": "Invalid username or password"}), 401
    login_user(user)
    profiles = [{"id": p.id, "name": p.name} for p in user.profiles]
    return jsonify({"ok": True, "username": user.username, "profiles": profiles})

@app.route("/api/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    return jsonify({"ok": True})

@app.route("/api/me")
def me():
    if not current_user.is_authenticated:
        return jsonify({"authenticated": False})
    profiles = [{"id": p.id, "name": p.name} for p in current_user.profiles]
    return jsonify({"authenticated": True, "username": current_user.username, "profiles": profiles})

# ── Profile routes ───────────────────────────────────────────────────────

@app.route("/api/profiles", methods=["GET"])
@login_required
def get_profiles():
    return jsonify([{"id": p.id, "name": p.name} for p in current_user.profiles])

@app.route("/api/profiles", methods=["POST"])
@login_required
def create_profile():
    data = request.get_json()
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Profile name required"}), 400
    profile = Profile(user_id=current_user.id, name=name)
    db.session.add(profile)
    db.session.commit()
    return jsonify({"id": profile.id, "name": profile.name})

@app.route("/api/profiles/<int:pid>", methods=["DELETE"])
@login_required
def delete_profile(pid):
    profile = Profile.query.filter_by(id=pid, user_id=current_user.id).first_or_404()
    db.session.delete(profile)
    db.session.commit()
    return jsonify({"ok": True})

# ── Entry routes ─────────────────────────────────────────────────────────

def get_profile_or_403(pid):
    profile = Profile.query.filter_by(id=pid, user_id=current_user.id).first()
    if not profile:
        return None
    return profile

@app.route("/api/profiles/<int:pid>/entries", methods=["GET"])
@login_required
def get_entries(pid):
    profile = get_profile_or_403(pid)
    if not profile:
        return jsonify({"error": "Forbidden"}), 403
    return jsonify([e.to_dict() for e in profile.entries])

@app.route("/api/profiles/<int:pid>/entries", methods=["POST"])
@login_required
def add_entry(pid):
    profile = get_profile_or_403(pid)
    if not profile:
        return jsonify({"error": "Forbidden"}), 403
    data = request.get_json()
    title = (data.get("title") or "").strip()
    if not title:
        return jsonify({"error": "Title required"}), 400
    existing = Entry.query.filter_by(profile_id=pid, title=title).first()
    if existing:
        return jsonify({"error": "already_exists", "entry": existing.to_dict()}), 409
    entry = Entry(
        profile_id=pid, title=title,
        media_type=data.get("type"), genres=",".join(data.get("genres") or []),
        runtime=data.get("runtime"), rating=data.get("rating"),
        year=data.get("year"), poster=data.get("poster"), plot=data.get("plot"),
        custom_desc=data.get("custom_desc"),
    )
    db.session.add(entry)
    db.session.commit()
    return jsonify(entry.to_dict()), 201

@app.route("/api/entries/<int:eid>", methods=["PATCH"])
@login_required
def update_entry(eid):
    entry = Entry.query.get_or_404(eid)
    if entry.profile.user_id != current_user.id:
        return jsonify({"error": "Forbidden"}), 403
    data = request.get_json()
    if "watched" in data:    entry.watched     = data["watched"]
    if "title" in data:      entry.title       = data["title"]
    if "type" in data:       entry.media_type  = data["type"]
    if "genres" in data:     entry.genres      = ",".join(data["genres"] or [])
    if "runtime" in data:    entry.runtime     = data["runtime"]
    if "rating" in data:     entry.rating      = data["rating"]
    if "year" in data:       entry.year        = data["year"]
    if "poster" in data:     entry.poster      = data["poster"]
    if "plot" in data:       entry.plot        = data["plot"]
    if "custom_desc" in data: entry.custom_desc = data["custom_desc"]
    db.session.commit()
    return jsonify(entry.to_dict())

@app.route("/api/entries/<int:eid>", methods=["DELETE"])
@login_required
def delete_entry(eid):
    entry = Entry.query.get_or_404(eid)
    if entry.profile.user_id != current_user.id:
        return jsonify({"error": "Forbidden"}), 403
    db.session.delete(entry)
    db.session.commit()
    return jsonify({"ok": True})

@app.route("/api/entries/bulk-delete", methods=["POST"])
@login_required
def bulk_delete():
    data = request.get_json()
    ids = data.get("ids", [])
    for eid in ids:
        entry = Entry.query.get(eid)
        if entry and entry.profile.user_id == current_user.id:
            db.session.delete(entry)
    db.session.commit()
    return jsonify({"ok": True, "deleted": len(ids)})

# ── OMDB helpers ─────────────────────────────────────────────────────────

def omdb_get(params):
    params["apikey"] = OMDB_API_KEY
    r = requests.get("http://www.omdbapi.com/", params=params, timeout=10)
    r.raise_for_status()
    return r.json()

def parse_omdb(d, original_title=None):
    rating = None
    raw = d.get("imdbRating", "N/A")
    if raw and raw != "N/A":
        try: rating = float(raw)
        except ValueError: pass

    runtime = d.get("Runtime", "N/A")
    runtime = None if runtime == "N/A" else runtime
    genres = [g.strip() for g in d.get("Genre", "").split(",") if g.strip()][:2]

    omdb_type = d.get("Type", "")
    total_seasons = d.get("totalSeasons")
    if omdb_type == "movie":
        media_type = "Movie"
    elif omdb_type in ("series", "episode"):
        media_type = "Series"
        if total_seasons and total_seasons != "N/A":
            try:
                n = int(total_seasons)
                runtime = f"{n} season{'s' if n != 1 else ''}"
            except ValueError: pass
    else:
        media_type = "Series"

    if "Animation" in genres and omdb_type == "series":
        media_type = "Anime"
    if "Documentary" in genres:
        media_type = "Documentary"

    plot   = d.get("Plot",   ""); plot   = "" if plot   == "N/A" else plot
    poster = d.get("Poster", ""); poster = "" if poster == "N/A" else poster

    return {
        "title":  d.get("Title", original_title or ""),
        "found":  True,
        "rating": rating,
        "genres": genres,
        "runtime": runtime,
        "type":   media_type,
        "year":   d.get("Year", ""),
        "poster": poster,
        "plot":   plot,
    }

@app.route("/api/fetch-info", methods=["POST"])
def fetch_info():
    if not OMDB_API_KEY:
        return jsonify({"error": "OMDB_API_KEY not set"}), 500
    data = request.get_json()
    title = (data.get("title") or "").strip()
    if not title:
        return jsonify({"error": "No title"}), 400
    d = omdb_get({"t": title, "plot": "short"})
    if d.get("Response") == "False":
        sd = omdb_get({"s": title})
        if sd.get("Response") == "True" and sd.get("Search"):
            d = omdb_get({"i": sd["Search"][0]["imdbID"], "plot": "short"})
        else:
            return jsonify({"title": title, "found": False})
    return jsonify(parse_omdb(d, title))

@app.route("/api/search", methods=["POST"])
def search_omdb():
    if not OMDB_API_KEY:
        return jsonify([])
    data = request.get_json()
    query = (data.get("query") or "").strip()
    if not query:
        return jsonify([])
    sd = omdb_get({"s": query})
    if sd.get("Response") != "True":
        return jsonify([])
    results = []
    for item in sd.get("Search", [])[:6]:
        poster = item.get("Poster", "")
        if poster == "N/A": poster = ""
        results.append({"title": item.get("Title",""), "year": item.get("Year",""), "type": item.get("Type","").capitalize(), "poster": poster})
    return jsonify(results)

# ── Serve SPA ─────────────────────────────────────────────────────────────

@app.route("/")
def home():
    return send_from_directory(app.static_folder, "auth.html")

@app.route("/app")
def main_app():
    return send_from_directory(app.static_folder, "index.html")

@app.route("/static/<path:path>")
def static_files(path):
    return send_from_directory(app.static_folder, path)

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True, port=5000)
