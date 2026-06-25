# ⚡ Real Pophran C.F. — Club Management System

> *"Every Match-Day is an opportunity to prove yourself."*

A full-stack sports analytics web application built to manage, track, and visualize player performance for my football club — **Real Pophran C.F.**

---

## 🖥️ Live Preview

| Player Analytics | Leaderboard |
|---|---|
| ![Player Analytics](screenshots/Player-analytics.png) | ![Leaderboard](screenshots/player-ranking.png) |

| Player Identity Card | Performance History |
|---|---|
| ![Player Profile](screenshots/players-profile.png) | ![Match History](screenshots/performance-history.png) |

| Manager Control Panel | Club Team Center |
|---|---|
| ![Manager Portal](screenshots/manager-portal.png) | ![Team Center](screenshots/club-performance.png) |

| AI Coach Matrix |
|---|
| ![Log Match](screenshots/log-match.png) |

---

## ⚙️ Tech Stack

| Layer | Technology |
|---|---|
| **Backend** | FastAPI (Python) |
| **Database** | SQLite |
| **Auth** | JWT Tokens + Passlib (pbkdf2_sha256) |
| **Frontend** | Vanilla HTML / CSS / JavaScript |
| **Charts** | Chart.js |
| **AI Feature** | Claude API (AI Coach Matrix) |

---

## 🚀 Features

### 👤 Player Features
- Secure registration & JWT-based login
- **Player Identity Card** — FIFA-style card with position, age, preferred foot, bio & avatar
- **Player Analytics Dashboard** — Match-day stats with live Goal, Assist & Rating charts
- **Performance History** — Full match timeline with dates, format & manager ratings
- **Log Match Performance** — Submit stats and get instant AI coaching feedback
- **Leaderboard** — Live rankings with Top Scorer, Top Assister, Best Rated & Most Improved badges

### 🛡️ Manager Features
- Dedicated Manager Control Panel
- Review and approve pending player stat submissions
- Assign official ratings (1–10) per match
- Points multiplier system: `Practice 0.5×` · `League 1.0×` · `Main Match 2.0×`

### 🏟️ Club Features
- **Club Team Center** — Squad-wide goals, assists, avg rating & Club MVP
- Real-time leaderboard with total points ranking

### 🤖 AI Coach Matrix
- After every match log, an AI coach analyses the player's performance
- Gives tactical feedback and an expected manager rating prediction
- Powered by the Claude API

---

## 📁 Project Structure

```
real-pophran-cf/
├── main.py          # FastAPI backend — all API routes
├── db_setup.py      # Database initialization & schema
├── index.html       # Full frontend (SPA — vanilla JS)
├── README.md
└── screenshots/     # App preview images
```

---

## 🏃 How to Run Locally

**1. Install dependencies**
```bash
pip install fastapi uvicorn passlib python-jose
```

**2. Initialize the database**
```bash
python db_setup.py
```

**3. Start the server**
```bash
uvicorn main:app --reload
```

**4. Open in browser**
```
http://localhost:8000
```

> Default Manager login — Username: `Kaif` | Password: set during db_setup

---

## 🔐 Security
- Passwords hashed using **pbkdf2_sha256** via Passlib
- All protected routes use **JWT token verification**
- Role-based access control — Players and Managers have separate permissions
- Stats can only be submitted by authenticated Players
- Ratings can only be approved by authenticated Managers

---

## 📊 Points System

| Match Format | Multiplier | Example (Rating 8.0) |
|---|---|---|
| Practice Session | ×0.5 | 4.0 pts |
| R.P.C.F League | ×1.0 | 8.0 pts |
| Main Match | ×2.0 | 16.0 pts |

---

## 👨‍💻 Built By

**Kaif Gawandi**
[GitHub](https://github.com/kaifgawandi) · [LinkedIn](https://www.linkedin.com/in/kaif-gawandi)

---

> Built with passion for Real Pophran C.F. ⚡
