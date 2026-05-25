# CLAUDE.md — ConExperiment 2.0

## Project Overview

An online experiment platform for communication/media research studying human-AI vs human-human conversation under different task types (emotional vs functional). Built from scratch to replace an oTree-based system that had concurrency limitations.

**Tech Stack**: Python / FastAPI / Jinja2 / Alpine.js / PostgreSQL / Redis / WebSocket / litellm

**Experimental Design**: 2×2×2 factorial (Task Type × Partnership HHC/HMC × Partner Label chatbot/human), **two-round** conversation design with deception manipulation.

## Language Rules

- All code comments in **English**
- All platform UI text in **English**
- Variable/function naming: Python `snake_case`
- This file and USER_GUIDE.md in **Chinese**（供研究者阅读）

## Complete Experiment Flow

```
[Start]
  │
  ▼
Consent ─── No ──→ EndNoConsent (退出, finished=False)
  │ Yes
  ▼
Welcome (Prolific ID + 头像选择 + 昵称)
  │
  ▼
TaskPriming (热身写作, ≥10 词)
  │
  ▼
ChatInstructions (Round 1) ─── 按 taskType × partnerLabel 显示 4 种文本
  │
  ├── 所有参与者 → WaitingRoom
  │     ├─ HHC: 真人配对 (120s 超时回退 HMC, 使用 partner_label 身份)
  │     └─ HMC: 虚假等候室 (5-15s 假装配对, 直接与 AI 对话)
  │
  ▼
ChatInstructions (Round 2) ─── 按 taskType 显示 2 种文本
  │
  ├── 所有参与者 → WaitingRoom
  │     ├─ 匹配成功 ──→ 与真人对话
  │     └─ 120s 超时 ──→ 回退 HMC (强制 MyBot 身份, 明确显示为 BOT)
  │
  ▼
SurveyPrompt (问卷说明页, 无表单)
  │
  ▼
SurveyPageA (Agency×4 + FeelingHeard×4 + Engagement×4 = 12 题)
  │
  ▼
SurveyPageB (ManipCheck×1 + AIUsage×1 + AILiteracy×4 = 6 题)
  │
  ▼
SurveyPageC (Outcome Variables: 25 scales × 1-4 items = 80 题)
  │
  ▼
Demographics (age + gender + race + education + partisanship + Religiosity×4 = 9 项)
  │
  ▼
Payment (Prolific 完成码)
  │
  ▼
[End] (finished=True)
```

### 配对机制 (v1.6.0 更新)

**Round 1**:
- **HHC 参与者**: 进入真人配对队列，120s 内匹配成功 → 与真人对话；超时 → 回退到 HMC（`partnership` 改为 HMC，使用 partner_label 身份）
- **HMC 参与者**: 进入虚假等候室（5-15s 随机等待），假装配对成功后直接与 AI 对话

**Round 2**:
- **所有参与者**: 都进入真人配对队列尝试匹配
  - 匹配成功 → 与真人对话
  - 120s 超时 → 回退到 HMC（`partnership` 改为 HMC），**强制显示为 MyBot (AI Chatbot)**，不使用 fake human 身份

### Chat Controls

| Parameter | Value | Description |
|-----------|-------|-------------|
| `min_turns` | 5 | "Next" button disabled until 5 turns reached |
| `max_turns` | 15 | Chat auto-ends at 15 turns |
| `max_duration` | 600s (10 min) | Chat auto-ends on timeout |

## Condition × UI Mapping

### Instruction Texts

**Round 1** — 4 variants (taskType × partnerLabel):

| taskType | partnerLabel | AI Identity | Partner Name | Avatar | Instruction Summary |
|----------|-------------|-------------|-------------|--------|-------------------|
| emotionTask | chatbot | MyBot (AI) | MyBot | myBot.png | "You will chat with AI chatbot MyBot about emotions" |
| emotionTask | human | Tommy (fake human) | Tommy | fox.png | "You will chat with another participant Tommy about emotions" |
| functionTask | chatbot | MyBot (AI) | MyBot | myBot.png | "You will chat with AI chatbot MyBot about a task" |
| functionTask | human | Tommy (fake human) | Tommy | fox.png | "You will chat with another participant Tommy about a task" |

**Round 2** — 2 variants (taskType only, same as v1):

| taskType | Instruction Summary |
|----------|-------------------|
| emotionTask | "You will chat with another participant about emotions" |
| functionTask | "You will chat with another participant about a task" |

### Pairing Confirmed Page Texts

**Round 1**:
| Actual Mode | partnerLabel | Display |
|-------------|-------------|---------|
| HMC (fake match) | chatbot | "You are paired with MyBot" + myBot.png |
| HMC (fake match) | human | "You are paired with Tommy" + fox.png |
| HHC (matched) | chatbot | Shows real partner's avatar and nickname (told it's MyBot) |
| HHC (matched) | human | Shows real partner's avatar and nickname |
| HHC (timeout fallback) | chatbot | "Since nobody has joined yet, you are paired with an AI chatbot" + myBot.png |
| HHC (timeout fallback) | human | "Since nobody has joined yet, you are paired with an AI chatbot" + myBot.png |

**Round 2**:
| Actual Mode | Display |
|-------------|---------|
| HHC (matched) | Shows real partner's avatar and nickname |
| HHC (timeout fallback) | **"Since nobody has joined yet, you are paired with an AI chatbot"** + myBot.png (**强制 MyBot**) |
| HMC (from Round 1) | Same as Round 1 HHC |

### LLM Prompt Mapping (4 variants)

| taskType | partnerLabel | Prompt | Identity |
|----------|-------------|--------|----------|
| emotionTask | chatbot | CHARACTER_PROMPT_A | "You are a conversational AI named MyBot" |
| emotionTask | human | CHARACTER_PROMPT_Afake | "You are a conversational partner named Tommy" |
| functionTask | chatbot | CHARACTER_PROMPT_B | "You are a conversational AI named MyBot" |
| functionTask | human | CHARACTER_PROMPT_Bfake | "You are a conversational partner named Tommy" |

## Project Structure

```
ConExperiment2.0/
├── main.py                          # FastAPI entry, router registration, CORS, lifespan
├── config.py                        # Settings from env vars
├── database.py                      # SQLAlchemy engine, SessionLocal, Base
├── requirements.txt
├── alembic.ini                      # Database migration config
├── alembic/                         # Migration scripts
│
├── models/                          # SQLAlchemy ORM models
│   ├── __init__.py
│   ├── participant.py               # Participant (id, display_id, conditions, current_step, current_round, hhc_fallback, is_test, resume_token)
│   ├── chat.py                      # ChatRoom (round_number, turn_count, room_type) + ChatMessage
│   ├── survey.py                    # SurveyResponse (all Likert scales + demographics)
│   └── experiment.py                # ExperimentSession (event log + step tracking) + ExperimentConfig
│
├── routers/                         # Route handlers
│   ├── experiment.py                # Experiment flow (consent/welcome/priming/instructions/payment) + _advance_step() helper + /resume/{token}
│   ├── survey.py                    # Survey pages (4 pages: prompt/pageA/pageB/demographics)
│   ├── chat.py                      # Chat page + pairing confirmed + HTTP endpoints
│   ├── admin.py                     # Admin dashboard, test tools, config, export (with single-password auth)
│   ├── errors.py                    # 404/500 error pages + global exception handler
│   └── ws.py                        # WebSocket (chat + matchmaking + admin monitor)
│
├── services/                        # Business logic
│   ├── __init__.py
│   ├── condition.py                 # Min-quota condition assignment (8 conditions)
│   ├── matchmaking.py               # HHC pairing (Redis Sorted Set) + 120s timeout fallback
│   ├── llm.py                       # LLM service (litellm + semaphore + fallback response)
│   ├── prolific.py                  # Prolific (URL params + duplicate check + completion callback)
│   ├── redis_pubsub.py              # Redis Pub/Sub cross-process WebSocket broadcast
│   ├── monitoring.py                # Event logging, step duration tracking, stuck detection
│   ├── scales.py                    # Scale registry (LikertScale with display_title + CustomItem + helpers)
│   └── export.py                    # CSV export (participant wide table + chat long table)
│
├── schemas/                         # Pydantic request/response models
│   ├── participant.py               # ParticipantCreate, ParticipantResponse
│   ├── chat.py                      # ChatMessageCreate, ChatEndRequest
│   ├── survey.py                    # validate_likert_fields(), DemographicsSubmit
│   └── admin.py                     # AdminLogin, ConfigUpdate, ExportRequest
│
├── templates/                       # Jinja2 HTML templates
│   ├── macros/
│   │   └── likert.html              # Jinja2 macros for Likert scale rendering
│   ├── base.html                    # Base layout (Alpine.js CDN)│   ├── consent.html                 # Consent form
│   ├── end_no_consent.html          # Decline exit page
│   ├── welcome.html                 # Prolific ID + avatar selection + nickname
│   ├── priming.html                 # Priming writing (≥10 words)
│   ├── instructions.html            # Instructions (R1: 4 variants; R2: 2 variants)
│   ├── waiting.html                 # HHC waiting room
│   ├── pairing_confirmed.html       # Pairing confirmed (variant by condition)
│   ├── chat.html                    # Chat page (HHC + HMC, 5-15 turns, 10min)
│   ├── survey_prompt.html           # Survey instruction page (no form)
│   ├── survey_pageA.html            # Agency(4) + FeelingHeard(4) + Engagement(4)
│   ├── survey_pageB.html            # ManipCheck(1) + AIUsage(1) + AILiteracy(4)
│   ├── survey_pageC.html            # Outcome Variables (25 scales, 80 items)
│   ├── demographics.html            # Demographics(5) + Religiosity(4)
│   ├── payment.html                 # Prolific completion code
│   ├── 404.html / 500.html          # Error pages
│   └── admin/                       # Admin dashboard
│       ├── base.html
│       ├── login.html               # Admin login
│       ├── dashboard.html           # Real-time overview (stats, event feed, LLM stats, chat preview, stuck warnings)
│       ├── participants.html        # Participant list (with progress bars and View links)
│       ├── participant_detail.html  # Individual participant detail (conditions, chat history, survey, events, resume URL)
│       ├── data_export.html         # Data export (2 CSV formats, test data filter)
│       ├── config.html              # Config editor (prompts, model, parameters)
│       └── test_tools.html          # Test tools (create participants, HHC pair, step control)
│
├── static/
│   ├── css/main.css
│   ├── js/chat.js                   # WebSocket client (with reconnection + history restore)
│   └── avatar/
│       ├── myBot.png                # AI partner avatar (chatbot label, not selectable)
│       ├── fox.png                  # Fake human avatar (human label: Tommy); also selectable
│       ├── lion.png                 # Selectable participant avatar
│       ├── rabbit.png               # Selectable participant avatar
│       ├── tiger.png                # Selectable participant avatar
│       ├── img_sad.png              # Emotion task priming image
│       └── img_box.jpg              # Function task priming image
│
├── docker-compose.yml               # Local dev: PostgreSQL + Redis
├── .env.example
├── CLAUDE.md
└── USER_GUIDE.md
```

## Reference Project (ConExperiment v1)

The original oTree implementation is at `../ConExperiment/`. Key files to port:

| Feature | Source File | What to Extract |
|---------|-------------|-----------------|
| LLM Prompts | `chatHMC/__init__.py` | CHARACTER_PROMPT_A/Afake/B/Bfake, temp=0.4, model=gpt-4o-mini, timeout=10s |
| HHC Matching | `chatHHC/__init__.py` | group_by_arrival_time, 120s timeout, fallback to HMC |
| Second Round HHC | `chatHHC_2r/__init__.py` | Same as chatHHC but fallback to chatHMC_backup |
| HMC Fallback | `chatHMC_backup/__init__.py` | Backup HMC for round 2, MyBot only (no fake human) |
| Survey Scales | `survey/__init__.py` | 4 pages: Prompt + VariablePageA + VariablePageB + Demographics |
| Conditions | `Introduction/__init__.py` | itertools.product, consent decline → skip to end |
| Priming | `task1/__init__.py` | taskPriming, min 10 words |
| Instructions | `task1/`, `task2/` | 4 instruction variants by taskType × partnerLabel |
| Chat UI | `chatHMC/chatEmo.html` | JS message display, 5-15 turns, 10min timeout, partner avatar/name |
| CSS | `_static/global/` | Styles, layout |

## Development Setup

```bash
# 1. Start infrastructure
docker-compose up -d   # PostgreSQL + Redis

# 2. Install Python dependencies
pip install -r requirements.txt

# 3. Set environment variables
cp .env.example .env

# 4. Run database migrations
alembic upgrade head

# 5. Start development server (choose one method)

# Method A: CLI with typer (supports --demo flag)
python main.py run --reload

# Method B: Direct uvicorn
uvicorn main:app --reload --port 8000

# Access at http://localhost:8000
# API docs at http://localhost:8000/docs
```

### CLI Commands

The project includes a CLI powered by `typer` for convenient server management:

```bash
# Start server (normal mode)
python main.py run

# Start server in demo mode
python main.py run --demo

# Start server with custom host/port
python main.py run --host 0.0.0.0 --port 8080

# Start server with auto-reload (development)
python main.py run --reload

# Show version
python main.py version
```

**Demo Mode (`--demo` flag)**: Enables testing mode with reduced turns/timeouts and skips Prolific checks.

## Key Architecture Decisions

### Why FastAPI (not Django)
Explicit code, native async, built-in API docs. No Django "magic."

### Why Jinja2 + Alpine.js (not React SPA)
No Node.js build step. Single Python codebase. Researcher can edit HTML templates directly (same as oTree). Alpine.js (15KB) for reactive UI. Vanilla JS for WebSocket.

### WebSocket Architecture
- **HHC**: Both participants → `/ws/chat/{room_id}`. Messages broadcast via Redis Pub/Sub.
- **HMC**: User message → save → broadcast → LLM call → save → broadcast.
- **Matchmaking**: Redis Sorted Set queues. Background check every 3s pairs participants.
- **Cross-process broadcast**: Redis Pub/Sub (`redis_pubsub.py`). Short-term: single worker deploy.
- **Reconnection**: Frontend auto-reconnects (exponential backoff, max 5 attempts). History restored from DB.

### LLM Concurrency
- `asyncio.Semaphore(30)` limits concurrent calls
- Fully async — doesn't block other participants
- 10-second timeout per response
- Fallback response on failure: "I'm sorry, I'm having trouble responding right now."

### Condition Assignment
Min-quota strategy: always assign to the condition with fewest participants. Ties broken randomly. Ensures balanced 2×2×2 distribution.

### Scale Registry (v2.3)
All Likert scales defined in `services/scales.py` as `LikertScale` dataclass entries. Non-standard items (manip_check, ai_usage) defined as `CustomItem`. The router (`routers/survey.py`) uses `request.form()` + dynamic field extraction from the registry. Templates use Jinja2 macros (`templates/macros/likert.html`) for rendering. Export auto-generates headers from registry. Adding a new Likert scale only requires: (1) add DB columns in `models/survey.py` + migration, (2) add one `LikertScale(...)` entry to `LIKERT_SCALES`. Everything else auto-adapts.

`LikertScale` has two name fields: `title` (academic construct name, used in CSV export only) and `display_title` (neutral UI heading shown to participants). Set `display_title=""` to hide the section header entirely. This prevents exposing research variable names (e.g., "Agency", "Conversational Engagement") to participants.

### HHC Timeout Fallback
- Wait timeout: 120 seconds
- On timeout: mark `hhc_fallback=True`, keep `partnership=HHC` (for data analysis)
- Create HMC-type ChatRoom, display fallback message
- Prompt selection by partnerLabel (consistent identity):
  - partnerLabel=chatbot → MyBot prompt (CHARACTER_PROMPT_A/B)
  - partnerLabel=human → Tommy prompt (CHARACTER_PROMPT_Afake/Bfake)

### Page Recovery
Based on `participant.current_step`. On page load, redirect to current step. Steps: `consent → welcome → priming → instructions_r1 → chat_r1 → instructions_r2 → chat_r2 → survey_prompt → survey_a → survey_b → survey_c → demographics → payment`.

### Admin Authentication
Single-password session auth. Password hash in env var (`ADMIN_PASSWORD_HASH`). Session stored in Redis with 24h TTL.

### Prolific Integration
- URL params: `?PROLIFIC_PID={pid}&SESSION_ID={sid}&STUDY_ID={study_id}`
- Duplicate detection: `prolific_id` unique constraint in DB
- Completion callback: POST to `PROLIFIC_COMPLETION_URL` on payment page

## Data Export Formats

### Participant Wide Table (one row per participant)
```
display_id, prolific_id, task_type, partnership, partner_label,
partner_label_check, current_round, hhc_fallback, is_finished, is_timeout,
sen_a_1~4, fee_h_1~4, ce_1~4, ail_1~4, ai_usage,
cga_1~2, cinf_1~2, ccg_1~3, cmu_1, cpu_1~4, ccs_1~4, cconn_1~4, cenj_1~3, cfsi_1,
pce_1~4, pca_1~4, pael_1~4, pta_1~4, psa_1~4, phom_1~4, psos_1~2, pwca_1~2, pwsa_1~2,
plik_1~4, pec_1~3, ppec_1~3, dhm_1~4, iri_pt_1~4, iri_ec_1~4, iri_pd_1~4,
age, gender, race, education, partisanship, rlg_1~4,
chat_r1_turns, chat_r1_duration, chat_r2_turns, chat_r2_duration,
created_at
```

### Chat Message Long Table (one row per message)
```
message_id, display_id, room_id, round_number, room_type, task_type,
sender_role, text, turn_number, created_at
```

## Error Handling

| Scenario | Handling |
|----------|----------|
| Page refresh / browser close | Auto-recover via `current_step` |
| WebSocket disconnect | Auto-reconnect (exponential backoff, max 5); restore chat history from DB |
| LLM call failure | Fallback response + error log; chat continues |
| Prolific ID duplicate | Reject entry, show "You have already participated" |
| Unauthorized admin access | Redirect to login page |
| 404 / 500 | Custom error pages |

## Common Tasks

### Add/modify survey item
1. `models/survey.py` — add/remove Column
2. `services/scales.py` — add/remove `LikertScale(...)` entry in `LIKERT_SCALES` (or `CustomItem` for non-standard items)
3. Run `alembic revision --autogenerate -m "description"` then `alembic upgrade head`

> Schema validation, router handling, template rendering, and CSV export all auto-adapt from the scale registry. No other files need changes for standard Likert scales.

### Change LLM prompt
Admin Dashboard → Config Editor → edit prompt text. No code change.

### Switch LLM model
Admin Dashboard → Config Editor → change `default_model` (e.g., `gpt-4o-mini` → `claude-haiku-4-5`).

### Edit page layout/text
Directly edit HTML in `templates/`. Same experience as editing oTree templates.

### Modify chat controls (turns/duration)
Admin Dashboard → Config Editor → change `min_turns`, `max_turns`, `max_duration`.

### Toggle demo mode
Set `DEMO_MODE=true` in `.env` → restart server. Reduces turns/timeouts, skips Prolific checks.

### Export data
Admin Dashboard → Data Export → choose format. Check "Include test participants" to include test data (default: excluded).

### Create test participant
Admin → Test Tools → "Quick Create" (one-click HMC) or Advanced → "Create Test Participant" (custom conditions).

### Test HHC chat
Admin → Test Tools → "Quick Create HHC" (pair at chat, fastest) or "Matchmaking Flow Test" (full flow with waiting room).

## Coding Conventions

- **Python**: Type hints on all function signatures. Docstrings on services/routes.
- **Templates**: Jinja2 syntax. Alpine.js (`x-data`, `x-on`, `x-show`).
- **API**: RESTful. Consistent error format: `{"detail": "error message"}`.
- **WebSocket**: JSON with `type` field for message routing.
- **Database**: UTC timestamps. UUID primary keys. `display_id` (P-XXXX) for readability.
- **Logging**: Python `logging` module, structured JSON. Key events: experiment start/end, condition assignment, match success/timeout, LLM calls.
- **Template JS Safety**: Any template variable injected into a `<script>` block must use `| tojson` filter (e.g. `{{ p.nickname | tojson }}`), not raw `{{ p.nickname }}` or `'{{ p.nickname }}'`. This prevents JS syntax errors when user input contains quotes, backslashes, or newlines. See BUG-D4.

## Demo Mode

Enable demo/testing mode to reduce waiting time for testing and presentations.

### Method 1: CLI flag (Recommended)
```bash
python main.py run --demo
```

### Method 2: Environment variable
Set `DEMO_MODE=true` in `.env` or environment variables:
```bash
# Unix/Linux/Mac
export DEMO_MODE=true
uvicorn main:app --reload

# Windows CMD
set DEMO_MODE=true
uvicorn main:app --reload

# Windows PowerShell
$env:DEMO_MODE="true"
uvicorn main:app --reload
```

### Effects

| Setting | Normal | Demo Mode |
|---------|--------|-----------|
| `MIN_TURNS` | 5 | 2 |
| `MAX_TURNS` | 15 | 5 |
| `MAX_DURATION` | 600s | 120s |
| `HHC_TIMEOUT` | 120s | 10s |
| Prolific duplicate check | Enabled | Skipped |
| Prolific completion callback | Enabled | Skipped |

## Admin Dashboard (`/admin/dashboard`)

### Real-Time Stats (5s Auto-Refresh)
- Total / Completed / In-Progress / In-Chat participant counts
- **LLM Stats cards**: total calls + error rate (5s auto-refresh via `/api/admin/llm-stats`)
- Condition Distribution table (all 8 conditions)
- **Step Distribution table** (active participants by current step)
- **Active Chat Rooms table**: shows all active rooms with room type (HHC/HMC), round, turn count, duration, participant info, and "Peek" button for inline chat preview
- **Active Participants section**: mini progress bars for each active participant (color-coded: blue <40%, orange 40-80%, green >80%)
- **Stuck Participant Warning**: yellow banner when participants exceed step time limits (configurable per step)
- **Event Feed**: real-time scrolling event log (3s poll via `/api/admin/events`)
- Data fetched via `/api/admin/stats` API endpoint (admin session required)

### Participant Detail Page (`/admin/participant/{display_id}`)
- Condition badges + status indicators (Test, Finished, Timeout, HHC Fallback)
- **Resume URL**: copyable link to resume participant session
- **13-step progress bar** with highlighted current position
- **Step Duration History**: from/to/duration/limit/over-limit status
- **Chat History**: collapsible per room, messages with auto-refresh for active rooms
- **Survey Responses**: all questionnaire answers
- **Event History**: recent events for this participant

### Participant Resume URL
- Each participant gets a unique `resume_token` (64-char URL-safe token, ~256 bits entropy)
- `GET /resume/{token}` → sets participant cookie → redirects to their current step
- Useful for recovery after browser crash, or admin-initiated session resume
- Resume URL shown on participant detail page with copy button

### Monitoring Service (`services/monitoring.py`)
- `log_event()`: generic event logging to `ExperimentSession` table
- `log_step_entry()`: records step entry timestamp in Redis (`step_time:{pid}:{step}`, 24h TTL)
- `log_step_duration()`: records duration with over-limit flag
- `detect_stuck_participants()`: checks active participants against `STEP_TIME_LIMITS`
- `STEP_TIME_LIMITS` (seconds): consent(300), welcome(120), priming(600), instructions(120), survey(60-600), payment(120)

### Event Logging Points
| Event | Trigger Location | Metadata |
|-------|-----------------|----------|
| `participant_created` | experiment.py consent_submit | task_type, partnership, partner_label |
| `match_success` | ws.py HHC match | room_id, partner_display_id, round |
| `match_timeout` | ws.py HHC timeout | fallback_to, round |
| `chat_ended` | chat.py end_chat | room_type, round, turn_count, duration |
| `llm_call` | chat.py HMC handler | latency, success, model, turn_number |
| `survey_completed` | survey.py demographics_submit | — |
| `experiment_completed` | experiment.py payment | — |

### Active Chat Rooms Display
- HHC rooms grouped by shared `room_id`, showing both participants
- HMC rooms shown individually with participant info
- Color-coded room type badges (HHC: blue, HMC: orange)
- Real-time duration calculation from `started_at`
- "Peek" button for inline chat preview (fetches from `/api/admin/chat/{room_uuid}`)

## Admin Test Tools (`/admin/test-tools`)

### Quick Actions Bar
Three one-click buttons at the top:

1. **Quick Create (HMC, instructions_r1)**: One-click HMC test participant. Fastest for single-participant testing.
2. **Matchmaking Flow Test (HHC)**: Creates 2 HHC participants at instructions_r1. Open both in separate incognito windows to test full flow: instructions → waiting room → real matchmaking → chat.
3. **Quick Create HHC (Pair at Chat)**: Creates 2 HHC participants pre-matched at chat step. Open both URLs to immediately start chatting.

### Test Participant Dashboard
- Table showing all test participants: Display ID, Nickname, Task, Partnership, Current Step, Round
- **Inline actions**: Open / Next >> (advance step) / Delete
- Step values color-coded: chat (orange), instructions (blue), survey (purple)
- Auto-refreshes after create/delete/step operations

### Step Control
Jump any participant to a specific step. Dropdown selector auto-populated with test participants. Auto-creates HMC ChatRoom if jumping to a chat step.

### Advanced Tools (Collapsible)
- **Create Test Participant (Custom)**: specify conditions, start step, nickname, avatar
- **HHC Queue Status**: view/clear matchmaking queues

### Delete Test Participants
- Delete single: inline "Delete" button in dashboard table (with confirmation)
- Delete all: "Delete All Test Data" button at page bottom
- Both clear partner references, Redis queues, cascade to messages/surveys/sessions

### New API Endpoints (v1.7.0)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/admin/stats` | GET | Dashboard stats (5s auto-refresh). Returns: total, finished, active, in_chat, conditions, steps, active_rooms, active_participants (with progress %), stuck_participants |
| `/api/admin/test/quick-create` | POST | Create HMC test participant at instructions_r1. Returns: id, display_id, url, resume_url |
| `/api/admin/test/matchmaking-test` | POST | Create 2 HHC participants for full flow test |
| `/api/admin/test/next-step` | POST | Advance participant to next step |
| `/api/admin/test/participants` | GET | List all test participants with details |
| `/api/admin/test/participant-options` | GET | Test participants for dropdown selectors |
| `/api/admin/events` | GET | Event feed (supports `since` param for incremental polling, `limit` param) |
| `/api/admin/llm-stats` | GET | LLM call stats: total_calls, successful_calls, failed_calls, error_rate, recent_calls |
| `/api/admin/chat/{room_uuid}` | GET | Chat messages for a specific room (admin monitoring) |
| `/admin/participant/{display_id}` | GET | Participant detail page (conditions, chat, survey, events, resume URL) |
| `/resume/{token}` | GET | Resume participant session (set cookie → redirect to current step) |

### Security (2026-04-07 Update)
All `/api/admin/test/*` endpoints require valid admin session (401 if unauthorized).

### HHC Chat Fix (2026-04-09)

**初始问题**: HHC 条件下，两轮对话均无法看到自己发出或对方发出的消息。

**已修复的 Bug**:

| Bug | 问题 | 修复 |
|-----|------|------|
| BUG-01 | Redis pubsub 频道名前缀不匹配：订阅 `"chat:{room_id}"`，发布 `"chat:room:{room_id}"` | 统一使用 `CHAT_CHANNEL_PREFIX` 常量 |
| BUG-02 | 转发对方消息时 `sender_role` 未翻转（`"user"` → 应为 `"partner"`） | 硬编码 `"sender_role": "partner"` |
| BUG-03 | 使用 redis-py 4.x 已移除的 `Redis.subscribe()`/`Redis.listen()` API | 改用 `r.pubsub()` 方式，独立连接 |
| BUG-04 | `finally` 块中调用 `r.aclose()` 关闭了全局共享连接池 | 仅关闭专用 pubsub 连接 |
| BUG-05 | `/chat` 页面缺少 `room` 参数时未查找活跃房间，导致重定向循环 | 自动查找当前轮次的活跃房间 |
| BUG-06 | `waiting` 页面仅允许 HHC 参与者访问 | 统一等候室体验 |
| BUG-07 | `end_chat` 错误时参与者卡住无法继续 | 错误时仍推进步骤 |
| BUG-08 | HHC 房间缺少 `initial_shared_turns` 计算 | 从 Redis 获取共享消息数 |
| BUG-09 | 重连后消息重复（缺少 `msg_id` 去重） | echo 和历史消息均包含 `msg_id` |
| BUG-10 | `chat_end` POST 时最小轮次检查依赖前端状态，可被绕过 | 服务端校验 `min_turns` |
| BUG-11 | 直接使用 `aioredis.from_url()` 创建 pubsub 连接，未使用已有的 `create_pubsub()` | 改用 `redis_pubsub.py` 的 `create_pubsub()`，并包裹 try/except 使 pubsub 失败不致命 |
| BUG-12 | `listen_redis()` 仅捕获 `CancelledError`，其他异常静默杀死 partner 消息接收；主循环 `except Exception: break` 使单次瞬态错误永久终止聊天 | `listen_redis()` 捕获所有异常并记录日志；主循环改为 `continue`（容错恢复）；`bleach.clean()` 和 `db.commit()` 均有 try/except 保底 |
| BUG-13 | **`incr_hhc_message_count()` 和 `publish_chat_message()` 无 try/except，Redis 异常传播到外层 `except: continue` 跳过 echo，导致用户看不到任何消息** | Redis 操作全部包裹 try/except；echo 移到所有可能失败的操作之后，确保始终执行；Redis incr 失败时回退到本地 `room.turn_count`；`chat_end` 发布同样包裹保护 |
| BUG-14 | **HHC Turn 计数不按一来一回计算** | 已确认：Redis 共享计数器 `hhc_msg_count:{room_id}` 每 2 条消息 = 1 turn。`shared_turns = shared_msg_count // 2`。`chat.html` 显示 `sharedTurns`。 |
| BUG-15 | **刷新页面后对方消息消失** | HHC 每个参与者有独立 ChatRoom，对方消息仅通过 Redis pubsub 实时传递，从未持久化。修复：`listen_redis()` 收到对方消息后，以 `sender_role=partner` 存入本地 room，刷新时从 DB 恢复完整对话。`chat_page()` 的 `initial_shared_turns` 改为从 DB 消息数计算。`history_request` 先 `db.refresh(room)` 再发送。 |
| BUG-16 | **一方 end chat 另一方有概率无法 end chat** | `POST /chat/end` 仅关闭发起者的 room，未通知对方。修复：end_chat 处理器对 HHC room 发布 `partner_left` 消息到 Redis pubsub。 |
| BUG-17 | **一方结束对话，另一方无提示且无法退出** | 前端添加 `partner_left` 事件处理，显示 "Alice has left the conversation" 横幅 + "Leave Chat" 按钮。`leaveChat()` 调用 `/chat/end?partner_left=1` 绕过 min_turns 检查。后端 `end_chat` 检测 `partner_left` 参数时跳过 min_turns 校验。 |
| BUG-18 | **刷新页面后对方消息重复** | `listen_redis()` 转发对方消息时使用原始发送者的 `msg_id`，但 DB 中保存的是本地生成的 UUID。刷新时 INITIAL_MESSAGES（本地 UUID）和 history_request（本地 UUID）匹配，但实时消息用的是原始 UUID，两者不一致导致去重失败。修复：`listen_redis()` 保存本地消息后，使用 `str(partner_msg.id)` 作为转发 `msg_id`。 |
| BUG-19 | **Admin 页面无需登录即可访问** | `require_admin()` 返回 `RedirectResponse`，但 FastAPI 的 `Depends()` 不会中断路由执行，返回值被赋给 `_auth` 但被忽略。修复：所有 6 个 admin 页面路由添加 `if _auth: return _auth` 检查。 |
| BUG-20 | **HHC 对方消息在 DB 中重复保存** | 页面刷新时旧 WebSocket handler 的 `listen_redis()` 可能与新 handler 同时运行，导致同一条对方消息被两个 handler 各保存一次到 DB。修复：(1) `listen_redis()` 保存前查询 DB 去重（`sender_role=partner` + `turn_number`）；(2) 前端 `onopen` 仅在 `reconnectAttempts > 0` 时才发送 `history_request`（首次连接跳过，因 `INITIAL_MESSAGES` 已包含 DB 消息）；(3) `_handle_hhc_chat` 入口设置 Redis `hhc_handler:{pid}` 键标记活跃 handler。 |
| BUG-21 | **HHC 对方消息仍显示两次** | BUG-20 的修复不够彻底：(1) handler lock 仅打 warning，未真正阻止旧 `listen_redis()` 继续运行；(2) 前端去重依赖 `msg_id`，但两个 handler 生成不同 UUID 导致去重失败。修复：(1) 后端使用 handler generation counter（`hhc_handler_gen:{pid}`），新 handler 启动时写入新 generation，旧 `listen_redis()` 每处理一条消息前检查 generation 是否变化，变化则立即退出；(2) 前端始终以 `(turn_number, sender_role)` 对去重，不再依赖 `msg_id`。 |

**UI 改进 (v1.8.0)**:
- 聊天框上方添加对话 Instruction 提醒条（无头像，显示对话对象和任务类型）
- Instruction 页面移除头像显示（保留文字信息）
- `partner_label=human`（非 fallback）时，聊天中对方头像使用用户自己选择的 avatar（增强"与真人对话"的欺骗效果）
- HHC 等候超时回退时，`participant.partnership` 从 HHC 改为 HMC
- 服务器启动时显示 Admin dashboard 链接

**UI 改进 (v1.9.0)**:
- Instruction 页面：`partner_label=human` 时不再显示假伙伴名字（Tommy），仅显示 "another participant"
- Pairing Confirmed 页面：`partner_label=human` 时同样隐藏假名字
- 聊天 Instruction 提醒条增强：显示 Round 标题 + 伙伴身份 + 详细对话指导（情绪任务 vs 实用任务各有不同提示）
- BUG-20 修复：HHC 对方消息不再重复显示（DB 去重 + 前端 `history_request` 仅重连时发送）

**BUG-21 修复 (v1.9.1)**:
- HHC 对方消息重复显示的根本原因：页面刷新时旧 `listen_redis()` 协程未被终止，与新 handler 同时订阅 Redis pubsub，导致同一条消息被发送两次（不同 `msg_id`）
- 后端修复：`_handle_hhc_chat` 使用 handler generation counter（`hhc_handler_gen:{pid}`），新 handler 启动时写入新值，旧 `listen_redis()` 每次收到消息前检查 generation，不匹配则退出循环
- 前端修复：去重逻辑改为始终以 `(turn_number, sender_role)` 对判断，不再依赖 `msg_id`（避免不同 handler 产生不同 UUID 导致去重失败）

**前端改进**:
- 添加 WebSocket 连接状态指示器（Connected / Connecting... / Reconnecting... / Disconnected）
- `onmessage` 添加 try/catch，解析失败不再静默忽略
- `onerror` 添加 `console.error` 日志和状态更新
- `onclose` 区分重连中 vs 已断开状态
- BUG-15/17: 添加 `partner_left` 事件处理 + 对方离开通知横幅 + Leave Chat 按钮
- BUG-17: `leaveChat()` 函数支持在对方离开后直接退出（绕过 min_turns）

**Bug 修复 (v2.0.0, 2026-05-15)**:
- **BUG-22**: HHC 匹配超时竞态条件 — timeout fallback 前重新检查 `get_match_result()`，防止同时创建 HHC 和 fallback HMC room
- **BUG-A1 (Critical)**: `/admin/export/{format_type}` 端点缺少管理员认证 — 添加 `_verify_admin_session` 检查
- **BUG-C1 (High)**: Chat timeout + min_turns 死锁 — 前端 timeout 时传 `timeout=1` 参数，server 跳过 min_turns 检查
- **BUG-C4 (High)**: HHC 双重 `chat_end` 竞态跳过 survey_prompt — `end_chat` 只在 `current_step in (chat_r1, chat_r2)` 时才 advance step
- **BUG-H1 (Medium)**: Redis pubsub 连接泄漏 — `listen_redis` finally 块中添加 `pubsub_conn.aclose()`

**Bug 修复 (v2.1.0, 2026-05-22)**:
- **BUG-DB1 (Critical)**: `listen_redis` 与主循环共享同一 DB session — `listen_redis` 的 `commit()` 会意外 flush 主循环未完成的 `room.turn_count` 修改；`rollback()` 会撤销这些修改导致 turn_count 失步。修复：`listen_redis` 使用独立的 DB session (`listen_db`)。
- **BUG-21 .decode() regression**: `listen_redis` 中 generation counter 检查 `current_gen.decode()` 因 Redis 连接已设 `decode_responses=True`（返回 str 而非 bytes），导致 `AttributeError` 被 `except: pass` 静默吞掉，使 BUG-21 修复完全失效。修复：移除 `.decode()` 调用，直接比较字符串。
- **诊断日志**: HHC 聊天添加关键节点的详细日志（Redis counter、turn_number、partner relay），前端添加 dedup 丢弃的 `console.warn`。

**Bug 修复 (v2.2.0, 2026-05-23)**:
- **BUG-TURN (High)**: HHC turn 计数逻辑不准确 — `shared_msg_count // 2` 将任意 2 条消息算作 1 turn（如 A 发 3 条 B 发 1 条 = 2 turns，但实际只有 1 次完整交换）。修复：新增 per-participant Redis 计数器（`hhc_peer_msg:{room_id}:{pid}`），`complete_turns = min(A_count, B_count)`，即每人至少各发 1 条才算 1 turn。涉及 `services/matchmaking.py`（新增 `incr_hhc_peer_msg_count`/`get_hhc_peer_msg_count`）、`routers/chat.py`（HHC 消息处理、初始 turn 计算、end_chat min_turns 校验三处）。
- **BUG-DECEP (High)**: 对方离开聊天时 `partner_left` 通知暴露真实身份 — 后端发送 `data.sender_name`（真实昵称如 "Bob"），但 `partner_label=chatbot` 条件下应显示 "MyBot"。修复：前端改用 `this.partnerName`（Alpine.js 变量，已根据欺骗条件正确设置）。

**Bug 修复 (v2.0.x, 2026-05-21)**:
- **BUG-D1**: HMC 虚假配对等候室报错 "An error occurred" — `ws.py` Round 1 HMC 复用已有 room 时 `room_id` 变量未定义（仅在 `if not room` 分支中赋值）。修复：统一使用 `room.room_id or str(room.id)`
- **BUG-D2**: HHC 达到 max turns 无通知横幅/跳转 — HMC 有 `handleChatEnd('max_turns')` + 5 秒延迟 POST，但 HHC 后端仅广播 `chat_end` 后无延迟立即关闭连接。修复：HHC 广播 `chat_end` 后添加 3 秒延迟，让前端显示横幅并读取最终消息
- **BUG-D3**: Round 2 HHC 真实匹配错误显示 MyBot — `chat.html` instruction bar 和 `partnerAvatar/partnerName` 未区分 R2 HHC real match 与 R2 fallback。修复：R2 `partner_info` 存在时始终显示真实伙伴 nickname/avatar，不受 `partner_label` 影响
- **BUG-D4**: HHC/HMC 消息发不出（JS 语法错误）— `chat.html` 中 `userName: {{ p.nickname | tojson }}` 后遗漏逗号，导致整个 `chatApp()` 对象字面量语法错误，Alpine.js 无法初始化，`sendMessage` 不存在。修复：补逗号。同时所有模板中的 nickname 字符串均改用 `| tojson` 过滤，防止单引号等特殊字符破坏 JS 语法

**Bug 修复 (v2.3.0, 2026-05-25)**:
- **BUG-ENUM (Critical)**: Page B 提交后 500 Server Error — PostgreSQL ENUM 类型 `step` 缺少 `survey_c` 值。Python `Step` enum 已添加 `survey_c = "survey_c"`，但 Alembic autogenerate 不会检测 Python Enum 值变更，数据库 ENUM 未更新。错误信息：`invalid input value for enum step: "survey_c"`。修复：创建手动迁移 `35839de747e2_add_survey_c_to_step_enum.py`，使用 `ALTER TYPE step ADD VALUE IF NOT EXISTS 'survey_c'`。

**UI 优化 (v2.3.0)**:
- `LikertScale` 新增 `display_title` 字段：中性 UI 标题（如 "Partner Capabilities"），替代学术变量名（如 "Agency"）。设为空字符串则不显示标题。`title` 字段保留用于 CSV 导出。
- Page A 三个量表设置中性 `display_title`：Agency → "Partner Capabilities"，Feeling Heard → "Feeling Heard"（不变），Conversational Engagement → "Conversation Experience"
- Page B/C/Demographics 所有量表 `display_title=""`，无标题直接显示题目
- Likert CSS 重写：`flex: 1` 等间距排列、锚定文字（"Strongly Disagree" / "Strongly Agree"）、选中状态绿色高亮（`:has(input:checked)`）
- `survey_pageB.html` 的 AI Usage 题目改用标准 Likert CSS 类（`likert-option`、`likert-anchor`），添加 "Never" / "Very frequently" 锚定标签

## Security Notes

- Prolific IDs encrypted at rest (Fernet)
- WebSocket connections authenticated via participant token
- User input sanitized (bleach) to prevent XSS in chat
- Admin panel protected by single-password session auth (BUG-19 fix: `require_admin` now properly enforced via `if _auth: return _auth` in all 6 page routes)
- **BUG-A1 fix (v2.0.0)**: `/admin/export/{format_type}` now requires admin session (`_verify_admin_session` check added)
- No CORS config needed (same-origin templates)

## Deployment (Render)

```bash
# Render auto-deploys on git push
# Required env vars in Render Dashboard → Environment:
DATABASE_URL, REDIS_URL, SECRET_KEY, OPENAI_API_KEY,
ANTHROPIC_API_KEY (optional), PROLIFIC_COMPLETION_URL, ENCRYPTION_KEY,
ADMIN_PASSWORD_HASH

# Single worker constraint (avoid WebSocket cross-process issues)
# Render → Web Service → Build Command: pip install -r requirements.txt
# Render → Web Service → Start Command: uvicorn main:app --host 0.0.0.0 --port $PORT --workers 1

# Redis: Render → Redis (managed service)
# PostgreSQL: Render → PostgreSQL (managed service)
```

## Pending Tasks / To-Do

- [ ] **页面停留超时检测（丢失用户标记）**: 为每个实验页面（consent、welcome、priming、instructions、waiting、chat、survey 等）添加合理的停留时长限制。超时未离开的 participant 标记为 `is_timeout=True`（异常用户），自动从配对队列中移除，不再参与后续聊天配对。`is_timeout` 字段已存在于 `Participant` 模型中，需在 `Chat Controls` 表中补充各页面超时阈值，后端通过中间件或页面级定时检测实现。

- [ ] **聊天时长异常标记**: Active Chat Rooms 持续时间超过 `max_duration` 时，自动将对应 ChatRoom 和 Participant 标记为异常数据。当前 `chat.html` 前端倒计时已到 0 时会自动 `handleChatEnd('timeout')`，但后端 `end_chat` 处理器已覆盖此场景。需在 admin dashboard 轮询接口 `/api/admin/stats` 中添加自动检测（`started_at` + `max_duration < now`），将超时长房间标记为 `is_timeout=True`。数据导出时异常记录需可筛选。

## Pairing Mechanism Design Verification (v2.0)

### Round 1 Partner Identity × Partner Label Matrix

| 实际模式 | partner_label=chatbot | partner_label=human |
|---------|----------------------|---------------------|
| **HMC** (直接AI) | 假等待 → MyBot (CHARACTER_PROMPT_A/B) | 假等待 → MyBot (CHARACTER_PROMPT_Afake/Bfake, 伪装 Tommy) |
| **HHC** (真人配对成功) | 真人对话 (UI 显示 MyBot 身份) | 真人对话 (UI 显示真人身份) |
| **HHC timeout fallback** | AI MyBot (CHARACTER_PROMPT_A/B) | AI MyBot (CHARACTER_PROMPT_Afake/Bfake, 伪装 Tommy) |

### Round 2 Logic
- **所有参与者**都尝试真人配对（按 task_type 分组，不按 partner_label）
- 匹配成功 → 真人对话
- 超时 fallback → **强制 MyBot 身份**（`force_chatbot` Redis flag），不再伪装，显示 "Since nobody has joined yet, you are paired with an AI chatbot"，使用 CHARACTER_PROMPT_A/B

### Key Design Decisions
- HHC 配对**不按 partner_label 分组**：欺骗实验中双方的 UI 各自根据自己条件渲染，互不影响
- Round 1 fallback **保留原始 partner_label**：用于选择对应的 LLM prompt（维持欺骗一致性）
- Round 2 fallback **强制 chatbot**：不使用 fake human prompt，明确告知参与者是与 AI 对话
- 条件分配使用 **min-quota 策略**：保证 8 组间被试数量平衡

## Monitoring Enhancement (v2.0, 2026-05-14)

**新增功能**:
- **参与者恢复链接**: 每个 participant 自动生成唯一 `resume_token`，支持 `/resume/{token}` 恢复会话
- **进度条**: Dashboard 和 Participants 列表页显示彩色进度条（13步进度追踪）
- **步骤停留时长**: `_advance_step()` helper 自动记录每步停留时长，支持超限检测
- **实时事件流**: Dashboard Event Feed 每 3 秒轮询，显示 match/timeout/LLM/survey 等事件
- **LLM 调用监控**: HMC 聊天中记录每次 LLM 调用（延迟、成功/失败），Dashboard 实时显示统计
- **聊天监控**: Dashboard Active Rooms 支持 "Peek" 预览聊天内容；Participant Detail 页面显示完整聊天历史
- **卡住检测**: 超过步骤时长限制的参与者自动触发黄色警告横幅

**新增文件**:
- `services/monitoring.py`: 事件日志、步骤时长、卡住检测
- `templates/admin/participant_detail.html`: 参与者详情页
- `alembic/versions/b70ace7d4d4f_add_resume_token_and_step_columns.py`: DB 迁移

**修改文件**:
- `models/participant.py`: +`resume_token` 列
- `models/experiment.py`: +`step` 列 (ExperimentSession)
- `routers/experiment.py`: +`_advance_step()` helper, +`/resume/{token}` route
- `routers/chat.py`: +事件日志（chat_ended, llm_call）
- `routers/survey.py`: 使用 `_advance_step()` 替代直接赋值
- `routers/ws.py`: +事件日志（match_success, match_timeout）
- `routers/admin.py`: +参与者详情页, +事件/LLM/聊天监控 API, +卡住检测
- `templates/admin/dashboard.html`: +进度条, +事件流, +LLM统计, +卡住警告, +聊天预览
- `templates/admin/participants.html`: +进度条, +View 链接

## Deliverables

- [x] Phase 1: Backend foundation (models, services, condition assignment, Redis, page recovery, admin auth)
- [x] Phase 2: All experiment pages (Jinja2 templates, condition × UI mapping, error pages)
- [x] Phase 3: HMC chat (WebSocket + LLM, 4 prompts, two-round flow, reconnection)
- [x] Phase 4: HHC chat (matchmaking, waiting room, timeout fallback)
- [x] Phase 5: Survey (4 pages) + Admin dashboard + Prolific integration + data export
- [x] Phase 6: Security + Deployment + Testing (encryption, sanitization, logging)
- [x] USER_GUIDE.md

### Version History

| Version | Date | Key Changes |
|---------|------|-------------|
| v1.0.0 | 2026-03 | Initial backend: models, FastAPI skeleton, basic routing |
| v1.5.0 | 2026-04 | All experiment pages, HMC chat, survey, admin dashboard |
| v1.6.0 | 2026-04 | HHC matchmaking + waiting room, two-round flow, timeout fallback |
| v1.7.0 | 2026-05 | Monitoring service, resume URL, participant detail, LLM stats |
| v1.8.0 | 2026-05 | Chat instruction reminder bar, UI polish, partnership fix on fallback |
| v1.9.0 | 2026-05 | Hide fake names in instructions/pairing, enhanced reminder bar |
| v1.9.1 | 2026-05 | BUG-21 fix: HHC dedup by (turn_number, sender_role) |
| v2.0.0 | 2026-05-15 | BUG-22, BUG-A1, BUG-C1, BUG-C4, BUG-H1; security hardening |
| v2.0.x | 2026-05-21 | Issue fix round: HMC fake pairing error, HHC max-turns banner, R2 display, JS escaping |
| v2.1.0 | 2026-05-22 | BUG-DB1: separate DB session for listen_redis; BUG-21 .decode() fix; diagnostic logging |
| v2.2.0 | 2026-05-23 | HHC per-participant turn counting (min(A,B)); deception breach fix (partner_left notification) |
| v2.3.0 | 2026-05-25 | Scale registry refactoring: `services/scales.py` + `templates/macros/likert.html`; add new Likert scales by editing 2 files only; new `survey_pageC.html` with 25 outcome variable scales (80 items); BUG-ENUM fix (PostgreSQL step ENUM missing `survey_c`); UI optimization: `display_title` hides academic variable names from participants; Likert CSS rewrite with equal spacing + selected state highlight |
