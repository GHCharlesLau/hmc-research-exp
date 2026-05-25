# ConExperiment 2.0

An online experiment platform for communication research studying **human-AI vs. human-human conversation** under different task types (emotional vs. functional) and partner identity conditions.

Built with Python / FastAPI / WebSocket to replace an oTree-based system that had concurrency limitations. Designed for deployment on [Prolific](https://www.prolific.com/) and supports real-time HHC (human-human) matchmaking with HMC (human-machine) fallback.

## Features

- **2x2x2 Factorial Design** -- Task Type x Partnership (HHC/HMC) x Partner Label (chatbot/human)
- **Two-Round Conversation** with deception manipulation and identity conditions
- **Real-Time HHC Matchmaking** via Redis Sorted Sets with 120s timeout fallback to AI
- **LLM-Powered Chat** via litellm (OpenAI, Anthropic, custom endpoints) with concurrency control
- **4-Page Survey System** with 80+ Likert items, scale registry, and automatic CSV export
- **Admin Dashboard** with real-time monitoring, LLM stats, chat preview, and test tools
- **Prolific Integration** -- URL params, duplicate detection, completion callbacks

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.11+, FastAPI, SQLAlchemy (async) |
| Frontend | Jinja2 templates, Alpine.js, vanilla WebSocket |
| Database | PostgreSQL 16 |
| Cache/Queue | Redis 7 |
| LLM | litellm (OpenAI GPT-4o-mini default) |
| Deployment | Render (single-worker uvicorn) |

## Quick Start

### Prerequisites

- Python 3.11+
- Docker & Docker Compose (for local PostgreSQL + Redis)
- An OpenAI API key (or compatible LLM endpoint)

### 1. Clone and Install

```bash
git clone https://github.com/GHCharlesLau/hmc-research-exp.git
cd hmc-research-exp
pip install -r requirements.txt
```

### 2. Start Infrastructure

```bash
docker-compose up -d    # PostgreSQL + Redis
docker-compose ps       # Verify both services are running
```

### 3. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` with your values:

| Variable | Required | Description |
|----------|----------|-------------|
| `SECRET_KEY` | Yes | Random string for session security |
| `DATABASE_URL` | Yes | PostgreSQL connection string (any driver prefix OK, auto-converted) |
| `REDIS_URL` | Yes | Redis connection string |
| `LLM_API_BASE` | Yes* | Primary LLM gateway URL (e.g. `https://api.n1n.ai/v1`) |
| `N1N_API_KEY` | Yes* | Primary LLM API key |
| `ENCRYPTION_KEY` | Yes | Fernet key for encrypting Prolific IDs at rest |
| `ADMIN_PASSWORD_HASH` | Yes | SHA256 hash of your admin password |
| `LLM_BACKUP_API_BASE` | No | Fallback LLM gateway URL |
| `LLM_BACKUP_API_KEY` | No | Fallback LLM API key |
| `LLM_BACKUP_MODEL` | No | Fallback model name (default: `gpt-4o-mini`) |
| `PROLIFIC_COMPLETION_URL` | No | Prolific study completion callback URL |
| `PROLIFIC_API_TOKEN` | No | Prolific API token |

*Or use `OPENAI_API_KEY` directly (without `LLM_API_BASE`) for the official OpenAI API.

**Generate keys:**

```python
# SECRET_KEY
import secrets; print(secrets.token_urlsafe(32))

# ENCRYPTION_KEY
from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())

# ADMIN_PASSWORD_HASH
import hashlib; print(hashlib.sha256(b"your-password").hexdigest())
```

### 4. Database Migration

```bash
alembic upgrade head
```

### 5. Run the Server

```bash
# Normal mode
python main.py run --reload

# Demo mode (reduced turns/timeouts for testing)
python main.py run --demo --reload
```

Access:
- Experiment: http://localhost:8000
- Admin Dashboard: http://localhost:8000/admin/login
- API Docs: http://localhost:8000/docs

## Experiment Flow

```
Consent
  |
  v
Welcome (Prolific ID + Avatar + Nickname)
  |
  v
Task Priming (Warm-up writing, >= 10 words)
  |
  v
Round 1 Instructions --> Waiting Room --> Chat (HHC or HMC)
  |
  v
Round 2 Instructions --> Waiting Room --> Chat (all try HHC)
  |
  v
Survey (4 pages: 12 + 6 + 80 + 9 items)
  |   Page A: Partner perceptions (12 items)
  |   Page B: Attention check + AI literacy (6 items)
  |   Page C: Conversation outcomes (80 items)
  |   Demographics: Age, gender, etc. + Religiosity (9 items)
  v
Payment (Prolific completion code)
```

### Pairing Mechanism

**Round 1:**
- **HHC participants**: Enter real matchmaking queue. Matched within 120s or fallback to HMC (AI chat).
- **HMC participants**: Fake waiting room (5-15s), then chat directly with AI.

**Round 2:**
- **All participants** attempt real HHC matchmaking.
- Timeout fallback forces **MyBot (AI) identity** -- no deception in Round 2 fallback.

## Project Structure

```
ConExperiment2.0/
├── main.py                  # FastAPI entry point + CLI (typer)
├── config.py                # Settings from environment variables
├── database.py              # SQLAlchemy async engine + session
├── docker-compose.yml       # Local dev: PostgreSQL 16 + Redis 7
├── alembic.ini              # Database migration config
├── requirements.txt
├── .env.example             # Environment variable template
│
├── models/                  # SQLAlchemy ORM models
│   ├── participant.py       # Participant + Step enum
│   ├── chat.py              # ChatRoom + ChatMessage
│   ├── survey.py            # SurveyResponse (all Likert + demographics)
│   └── experiment.py        # ExperimentSession + ExperimentConfig
│
├── routers/                 # FastAPI route handlers
│   ├── experiment.py        # Consent, welcome, priming, instructions, payment
│   ├── survey.py            # 4 survey pages (A/B/C/demographics)
│   ├── chat.py              # Chat page + HTTP endpoints
│   ├── admin.py             # Admin dashboard + export + test tools
│   ├── ws.py                # WebSocket (chat + matchmaking)
│   └── errors.py            # 404/500 error pages
│
├── services/                # Business logic
│   ├── scales.py            # Scale registry (LikertScale + CustomItem)
│   ├── matchmaking.py       # HHC pairing + Redis queues
│   ├── llm.py               # LLM service (litellm + semaphore)
│   ├── monitoring.py        # Event logging + stuck detection
│   ├── export.py            # CSV export (2 formats)
│   ├── prolific.py          # Prolific integration
│   └── redis_pubsub.py      # Redis Pub/Sub for cross-process broadcast
│
├── templates/               # Jinja2 HTML templates
│   ├── macros/likert.html   # Reusable Likert scale macros
│   ├── *.html               # 14 experiment pages
│   └── admin/               # 7 admin pages
│
├── static/
│   ├── css/main.css         # Complete design system
│   ├── js/chat.js           # WebSocket client
│   └── avatar/              # Avatar images
│
└── alembic/                 # Database migrations
```

## Adding a New Likert Scale

The scale registry architecture means adding a new Likert scale requires editing only **2 files**:

1. Add DB columns in `models/survey.py` and run migration:
   ```bash
   alembic revision --autogenerate -m "add_trust_scale"
   alembic upgrade head
   ```

2. Add one entry in `services/scales.py`:
   ```python
   LikertScale("trust", "C", "Trust", (
       "I trusted my conversation partner.",
       "My partner was trustworthy.",
   )),
   ```

Router, template rendering, validation, and CSV export all adapt automatically.

## Admin Dashboard

Access at `/admin/login` with your configured password.

### Key Features
- **Real-time stats** (5s auto-refresh): participant counts, condition distribution, step distribution
- **Active chat rooms**: live monitoring with inline message preview
- **LLM call stats**: total calls, error rate, latency tracking
- **Participant detail**: full history (conditions, chat, survey, events, resume URL)
- **Test tools**: one-click participant creation, step control, matchmaking testing
- **Data export**: participant wide table + chat message long table (CSV)
- **Config editor**: modify LLM prompts, model, chat controls without code changes

## Deployment on Render

### Option A: Blueprint (Recommended)

The repo includes a `render.yaml` Blueprint file. In Render Dashboard:

1. Click **"New" -> "Blueprint"**
2. Connect your GitHub repo (`GHCharlesLau/hmc-research-exp`)
3. Render auto-creates 3 services: Web Service + PostgreSQL + Redis
4. Fill in secret env vars in Dashboard -> Environment (see table below)
5. Deploy

### Option B: Manual Setup

1. **Web Service**: Connect your GitHub repo
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `bash start.sh` (runs `alembic upgrade head` then `uvicorn`)
   - **Workers MUST be 1** (WebSocket constraint)

2. **PostgreSQL**: Create managed PostgreSQL database (Starter plan)

3. **Redis**: Create managed Redis instance (Starter plan)

### Environment Variables

Set in Render Dashboard > Environment:

| Variable | Source | Description |
|----------|--------|-------------|
| `DATABASE_URL` | Auto-injected | Render PostgreSQL internal URL (`postgresql://`, auto-converted to `asyncpg`) |
| `REDIS_URL` | Auto-injected | Render Redis internal URL |
| `SECRET_KEY` | Manual | Generate: `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `LLM_API_BASE` | Manual | Primary LLM gateway URL (e.g. `https://api.n1n.ai/v1`) |
| `N1N_API_KEY` | Manual | Primary LLM API key |
| `LLM_BACKUP_API_BASE` | Manual | Fallback LLM gateway URL |
| `LLM_BACKUP_API_KEY` | Manual | Fallback LLM API key |
| `LLM_BACKUP_MODEL` | Optional | Default: `gpt-4o-mini` |
| `ENCRYPTION_KEY` | Manual | Generate: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `ADMIN_PASSWORD_HASH` | Manual | Generate: `python -c "import hashlib; print(hashlib.sha256(b'your-password').hexdigest())"` |
| `PROLIFIC_COMPLETION_URL` | Manual | Prolific study completion callback (set when going live) |
| `PROLIFIC_API_TOKEN` | Manual | Prolific API token (set when going live) |
| `DEBUG` | Default `false` | Set to `true` only for debugging |
| `DEMO_MODE` | Default `false` | Set to `true` for testing |

> **Note**: Render provides `DATABASE_URL` as `postgresql://user:pass@host/db`. The app automatically converts this to `postgresql+asyncpg://` for async operations. No manual URL editing needed.

## Demo Mode

For testing and presentations:

```bash
python main.py run --demo
```

| Setting | Normal | Demo |
|---------|--------|------|
| Min turns | 5 | 2 |
| Max turns | 15 | 5 |
| Max duration | 600s | 300s |
| HHC match timeout | 120s | 10s |
| Prolific checks | Enabled | Skipped |

## Data Export

Two CSV formats available via Admin Dashboard > Data Export:

1. **Participant Wide Table** -- one row per participant with all survey responses, demographics, chat statistics
2. **Chat Messages Long Table** -- one row per message with sender, text, timestamps

Test participants are excluded by default; toggle "Include test participants" to include them.

## Security

- Prolific IDs encrypted at rest (Fernet)
- Chat messages sanitized (bleach) to prevent XSS
- Admin panel protected by single-password session auth (Redis, 24h TTL)
- WebSocket connections authenticated via participant token
- Template variables in `<script>` blocks use `| tojson` filter to prevent JS injection

## FAQ

**Q: `relation does not exist` on startup?**
Run `alembic upgrade head` to apply database migrations.

**Q: Redis connection failed?**
Check Docker: `docker-compose ps` and `docker-compose restart redis`.

**Q: LLM not responding?**
Check `LLM_API_BASE` and `N1N_API_KEY` (or `OPENAI_API_KEY`) in `.env`. The system auto-falls back to the backup provider (`LLM_BACKUP_API_BASE`) if configured.

**Q: HHC matchmaking not working?**
You need at least 2 HHC participants simultaneously in the waiting room. If only 1 participant, they will timeout after 120s and fallback to HMC.

**Q: How to add a new experiment step (e.g., a new survey page)?**
After adding a new value to the `Step` enum in `models/participant.py`, you must create a **manual Alembic migration** with `ALTER TYPE step ADD VALUE IF NOT EXISTS 'new_step'`. Alembic autogenerate does not detect Python Enum changes.

## License

This project is for academic research use. Please contact the authors before reuse.

## Citation

If you use this platform in your research, please cite:

```
[Your paper citation here]
```

## Acknowledgments

- Built to replace [oTree](https://www.otree.org/)-based ConExperiment v1
- LLM integration powered by [litellm](https://github.com/BerriAI/litellm)
- Participant recruitment via [Prolific](https://www.prolific.com/)
