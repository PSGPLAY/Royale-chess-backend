# Royal Chess – Django Backend

Server-authoritative backend for Royal Chess built with **Django**, **Django REST Framework**, and **Django Channels**.

---

## Architecture Overview

* **Server-Authoritative Game Engine**: Uses `python-chess` on the server to validate legal moves, deployments, captures, promotions, and Royale Mode economy transactions.
* **Accounts & Profiles**: User registration, login token authentication, ELO rating, persistent currency, and player statistics.
* **Real-Time Multiplayer**: Django Channels WebSocket layer with Daphne ASGI routing.
* **Royale Mode Support**: Server-managed match currency, 3-slot dynamic shops, and turn skipping on rerolls.

---

## Directory Structure

```
backend/
├── config/             # Django project settings, ASGI & WSGI routing, root URLs
├── accounts/           # User authentication, profiles, ratings & leaderboard
│   ├── models.py       # PlayerProfile with ELO & persistent currency
│   ├── serializers.py
│   ├── views.py
│   └── urls.py
├── gameplay/           # Match management, chess engine & WebSockets
│   ├── models.py       # Match, MatchMove
│   ├── services/       # Server-authoritative python-chess rule engine
│   ├── serializers.py
│   ├── views.py        # REST API endpoints
│   ├── consumers.py    # Channels WebSocket consumer
│   ├── routing.py      # WebSocket URL patterns
│   └── tests.py        # Automated test suite
├── venv/               # Python virtual environment
├── manage.py
└── requirements.txt
```

---

## Quick Start

### 1. Activate Virtual Environment
```powershell
cd backend
.\venv\Scripts\Activate.ps1
```

### 2. Run Database Migrations
```powershell
python manage.py migrate
```

### 3. Run Development Server (ASGI / Channels support)
```powershell
python manage.py runserver
```
or with Daphne:
```powershell
daphne -b 127.0.0.1 -p 8000 config.asgi:application
```

### 4. Run Test Suite
```powershell
python manage.py test
```

---

## API Endpoints

### Authentication
* `POST /api/auth/register/` – Register user and obtain auth token
* `POST /api/auth/login/` – Log in and obtain auth token
* `POST /api/auth/logout/` – Log out
* `GET  /api/auth/profile/` – Get current player profile
* `GET  /api/auth/leaderboard/` – Top players by ELO

### Matches
* `POST /api/matches/create/` – Create a new match (`mode: "royale" | "normal"`)
* `GET  /api/matches/<uuid:match_id>/` – Retrieve match state & move history
* `POST /api/matches/<uuid:match_id>/move/` – Submit move (`from`, `to`, `promotion`)
* `POST /api/matches/<uuid:match_id>/deploy/` – Deploy piece from shop (`player`, `piece_type`, `square`)
* `POST /api/matches/<uuid:match_id>/reroll/` – Reroll 3 shop slots for 1 coin (`player`)
* `GET  /api/matches/history/` – Player's recent matches

### WebSockets
* `ws://127.0.0.1:8000/ws/match/<match_id>/` – Live match synchronization & chat

