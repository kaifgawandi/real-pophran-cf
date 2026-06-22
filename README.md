# Real Pophran C.F. — Club Management System

A full-stack web app built to manage my football club's stats, rankings, and match ratings.

## Tech Stack
- **Backend:** FastAPI (Python)
- **Database:** SQLite
- **Frontend:** Vanilla HTML/CSS/JS

## Features
- Player registration & login
- Submit match stats (goals & assists)
- Manager approval & rating system
- Live rankings leaderboard
- Points multiplier: Practice (0.5x) · League (1x) · Main (2x)

## Screenshots

### Login
![Login](ss-login.png)

### Player Dashboard
![Dashboard](ss-dashboard.png)

### Players Ranking
![Rankings](ss-rankings.png)

### Log Match-Day
![Log Match](ss-logmatch.png)

### Manager Control Panel
![Manager](ss-manager.png)

## How to Run
pip install fastapi uvicorn
python db_setup.py
uvicorn main:app --reload

Then open: http://localhost:8000
