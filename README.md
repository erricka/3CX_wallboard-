# AMK Call Center Wallboard (3CX)

Real-time call-center wallboard for 3CX v20 with downloadable daily reports, styled for AMK Bank
and built for a large office TV: overall figures for every call on the phone system on the left, up to 30 agents
on the right, all on one screen (from 1280 px wide; narrower screens stack them).

- **Frontend:** React (Vite), built into the same Docker image and served by the backend
- **Backend:** Python (FastAPI). Polls the 3CX XAPI and pushes updates over a WebSocket.
- **Database:** PostgreSQL. Stores daily stats, the call log, agent login sessions and the status history.
- **Brand:** AMK colours (#A53C6F, #5B0B30, #FFF2F9), fonts Lato and Kantumruy Pro (bundled, no internet
  needed on the TV), and the AMK logo from amkbank.com.kh in `frontend/src/brand/`. The AMK name and logo
  belong to AMK Bank Plc.

## How it works

```
3CX XAPI ──(every 3 s: Users, ActiveCalls; Queues every 60 s)──► backend ──WebSocket──► React wallboard
        └─(every 60 s: report functions for today)──► PostgreSQL ◄── /api/reports/daily (Excel / CSV)
```

At startup the backend also pulls the last 31 days into PostgreSQL, so even the "Last 1 month" report downloads quickly.
Finished days are fetched once and then served from the database. Today is refreshed every minute.

### Where every number comes from

| Wallboard column | Source |
|---|---|
| **Overall** tiles | Every call on the PBX today, from the call log (`ReportCallLogData`), one call per `MainCallHistoryId`. Total = inbound + outbound + internal (`Direction`). Answered = a person picked up (an extension, or the outside party of an outbound call); voicemail, call scripts and IVRs (`CallType` *System*) and queue hold music do not count. Inbound missed = rang an extension, queue or ring group but nobody answered. Answer rate = inbound answered ÷ (answered + missed). Avg talk time = talk time of answered calls ÷ answered calls. Avg wait time = how long answered inbound callers waited until a person picked up. Calls in progress = `ActiveCalls` right now. |
| Agent **Status** | `ActiveCalls`: the agent is on a call → **Talking**, or **Ringing**. Otherwise `Users.QueueStatus`: logged out → **Logoff**. Logged in with profile *Available* → **Ready**. Any other profile (Away, DND, …) shows the profile name. Phone not registered → **Offline**. |
| Agents listed | The members of the queues in `WALLBOARD_QUEUES` and the ring groups in `WALLBOARD_RING_GROUPS`. |
| Inbound calls | `ReportExtensionStatistics.InboundAnsweredCount` |
| Outbound calls | `OutboundAnsweredCount + OutboundUnansweredCount` |
| Missed calls (agent) | `InboundUnansweredCount` |
| Unanswered within 5 sec | Call log (`ReportCallLogData`): calls that rang the agent for more than 5 s, whether answered late or never. Queue legs are used, so queue waiting time is not counted. Counted once per call. The threshold is set with `SLOW_ANSWER_SECONDS`. |
| Work time | `ReportAgentLoginHistory`: the union of queue login sessions today, so overlapping queues count once. Ring group members have no queue login: for them it is the time the wallboard saw their phone online (so only while the wallboard is running). If the report is unavailable, the wallboard's own status history is used for everyone. |

All counters reset at 00:00 in `TIMEZONE` (default `Asia/Phnom_Penh`).

## 1. Create the 3CX API client

In the 3CX Admin Console: **Integrations → API → Add**.

- Client ID: e.g. `dashboardamk`
- Tick **XAPI Access Enabled**
- Department/role: one with access to the queues and agents you want to show (System Owner/Admin sees everything)
- Copy the API key. It is shown only once.

## 2. Configure

```bash
cp .env.example .env
# edit .env: THREECX_CLIENT_SECRET, POSTGRES_PASSWORD, and whose agents to list:
#   WALLBOARD_QUEUES (none = no queues), WALLBOARD_RING_GROUPS
```

`.env` is git-ignored. Never commit your API key.

## 3. Check the 3CX connection (recommended)

```bash
cd backend
pip install -r requirements.txt
python -m scripts.probe_3cx
```

The probe calls every endpoint the wallboard uses, prints `OK`/`FAIL` with the field names, and saves samples in `backend/probe-output/`.
If anything fails, the error message names the endpoint and the HTTP status.

## 4. Host it

GitHub Pages cannot run this app: Pages serves static files only, and the wallboard needs the Python backend and PostgreSQL.

### Option A: GitHub Codespaces (runs on GitHub, good for trying it out)

1. Give the codespace the API key, either way:
   - GitHub → **Settings → Codespaces → New secret**: name `THREECX_CLIENT_SECRET`, value = API key, repository = this repo, or
   - a `.env` file in the repo root (only in a **private** repo).
2. Repo page → **Code → Codespaces → Create codespace on main**.
3. The first start takes a few minutes. It installs everything, builds the React app, starts PostgreSQL and the wallboard.
4. Open the **Ports** tab and click the globe icon next to port **8000** (*Wallboard*).
   The port is private to your GitHub login. To share it: right-click → **Port visibility → Public**.

Server log: `cat /tmp/wallboard.log`. Restart: `bash .devcontainer/run.sh`.
A codespace stops after 30 minutes without activity (configurable in GitHub settings), and the wallboard stops with it.

### Option B: Render (free, always-on URL)

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/erricka/3cx_wallboard-)

1. Click the button and sign in to Render (a GitHub login works).
2. Render reads `render.yaml`. It creates a PostgreSQL database and the wallboard web service in Singapore.
3. When asked for `THREECX_CLIENT_SECRET`, paste the 3CX API key. Click **Apply**.
4. The first build takes about 5 minutes. Then open `https://3cx-wallboard-XXXX.onrender.com`.
5. Check `https://<your-url>/api/diagnostics`: every check should say `"ok": true`.

On the free plan, the service sleeps after 15 minutes with no visitors, and the database expires after 30 days.
For a wallboard on a TV all day, use the Starter plan (a few dollars a month) or option B.

### Option C: Docker on your own server or PC

On any machine that can reach `maxbit.3cx.asia`:

```bash
docker compose up -d --build
```

Open `http://<server>:8080`. Change the port with `WALLBOARD_PORT` in `.env`.
Logs: `docker compose logs -f app`. Probe: `docker compose run --rm app python -m scripts.probe_3cx`.

The wallboard has no login of its own. If it is on the public internet, restrict access: a VPN, an IP allow-list, or basic auth on a reverse proxy.

## Local development

```bash
# PostgreSQL running locally, then:
cd backend
pip install -r requirements-dev.txt
DATABASE_URL=postgresql+asyncpg://wallboard:wallboard@localhost:5432/wallboard \
  uvicorn app.main:create_app --factory --reload --port 8000

cd frontend
npm install
npm run dev        # http://localhost:5173, proxies /api and /ws to :8000
```

Tests: `cd backend && pytest`

## Reports

The **Download report** button on the wallboard, or
`GET /api/reports/daily?period=today|yesterday|7days|1month&format=xlsx|csv`,
or a custom **Date Range**: `period=range&start=2026-06-01&end=2026-10-10` (up to 366 days).
Days not stored yet are fetched from 3CX first, so a long range can take a minute the first time.

The Excel workbook has four sheets:

- **Summary**: overall totals (every call on the PBX) and totals per agent for the period
- **Daily Agents**: one row per agent per day (inbound, outbound, missed, unanswered within 5 sec, talk time, work time)
- **Daily Overall**: the overall figures per day (calls by direction, answered, missed, answer rate, talk and wait time)
- **Call Log**: every call on the PBX, with its direction

The CSV has the same overall and agent rows per day.

"Last 1 month" covers the last 30 days, including today.

## API

| Endpoint | |
|---|---|
| `GET /api/wallboard` | current snapshot (JSON) |
| `WS /ws/wallboard` | snapshot pushed on every poll |
| `GET /api/reports/daily` | report download |
| `GET /api/health` | health check |
| `GET /api/diagnostics` | tests every 3CX endpoint (status and field names only) |

## Database tables

`agents`, `queues`, `agent_daily_stats`, `queue_daily_stats`, `overall_daily_stats`, `call_records` (raw 3CX rows kept in `raw` JSONB), `agent_sessions`, `agent_status_log`, `synced_days`. They are created automatically on first start.
