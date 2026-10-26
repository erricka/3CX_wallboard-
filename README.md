# 3CX Real-time Wallboard

Live call-center wallboard for 3CX v20 with downloadable daily reports.

- **Frontend:** React (Vite), built into the same Docker image and served by the backend
- **Backend:** Python (FastAPI). Polls the 3CX XAPI and pushes updates over a WebSocket.
- **Database:** PostgreSQL. Stores daily stats, the call log, agent login sessions and the status history.

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
| Agent **Status** | `ActiveCalls`: the agent is on a call → **Talking**, or **Ringing**. Otherwise `Users.QueueStatus`: logged out → **Logoff**. Logged in with profile *Available* → **Ready**. Any other profile (Away, DND, …) shows the profile name. Phone not registered → **Offline**. |
| Agents in work / free / talk | Agents of the queue who are logged in / *Ready* / *Talking* |
| Calls waiting in queue, Max wait time | `ActiveCalls` whose callee is the queue and no agent is connected yet. Wait time = now − `LastChangeStatus`. |
| Answered / Missed calls (queue) | `ReportQueuePerformanceTotals` for today: answered = `ExtensionAnsweredCount`, missed = received − answered |
| Inbound calls | `ReportExtensionStatistics.InboundAnsweredCount` |
| Outbound calls | `OutboundAnsweredCount + OutboundUnansweredCount` |
| Missed calls (agent) | `InboundUnansweredCount` |
| Unanswered within 5 sec | Call log (`ReportCallLogData`): calls that rang the agent for more than 5 s, whether answered late or never. Queue legs are used, so queue waiting time is not counted. Counted once per call. The threshold is set with `SLOW_ANSWER_SECONDS`. |
| Work time | `ReportAgentLoginHistory`: the union of queue login sessions today, so overlapping queues count once. If that report is unavailable, the wallboard's own status history is used. |

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
# edit .env: THREECX_CLIENT_SECRET, POSTGRES_PASSWORD, optionally WALLBOARD_QUEUES
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

### Option A: Render (free, gives you a public URL)

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/erricka/3cx_wallboard-)

1. Click the button and sign in to Render (a GitHub login works).
2. Render reads `render.yaml`. It creates a PostgreSQL database and the wallboard web service in Singapore.
3. When asked for `THREECX_CLIENT_SECRET`, paste the 3CX API key. Click **Apply**.
4. The first build takes about 5 minutes. Then open `https://3cx-wallboard-XXXX.onrender.com`.
5. Check `https://<your-url>/api/diagnostics`: every check should say `"ok": true`.

On the free plan, the service sleeps after 15 minutes with no visitors, and the database expires after 30 days.
For a wallboard on a TV all day, use the Starter plan (a few dollars a month) or option B.

### Option B: Docker on your own server or PC

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
`GET /api/reports/daily?period=today|yesterday|7days|1month&format=xlsx|csv`.

The Excel workbook has four sheets:

- **Summary**: totals per queue and per agent for the period
- **Daily Agents**: one row per agent per day (inbound, outbound, missed, unanswered within 5 sec, talk time, work time)
- **Daily Queues**: received / answered / missed / answer rate per day
- **Call Log**: every call that involved the wallboard's queues or agents

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

`agents`, `queues`, `agent_daily_stats`, `queue_daily_stats`, `call_records` (raw 3CX rows kept in `raw` JSONB), `agent_sessions`, `agent_status_log`, `synced_days`. They are created automatically on first start.
