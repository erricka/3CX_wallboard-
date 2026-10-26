"""Daily statistics: pulled from 3CX report functions and stored in Postgres.

Per agent and day:
  inbound          answered inbound calls              (ReportExtensionStatistics)
  outbound         outbound calls made                 (ReportExtensionStatistics)
  missed           unanswered inbound calls            (ReportExtensionStatistics)
  unanswered_slow  calls that rang > N sec before being answered or dropped (call log)
  talk_seconds     inbound + outbound talking time     (ReportExtensionStatistics)
  work_seconds     time logged in to the queue(s)      (ReportAgentLoginHistory, or the
                                                       wallboard's own status log as fallback)
Per queue and day: received / answered / missed       (ReportQueuePerformanceTotals)
"""

import asyncio
import logging
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import delete, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .config import Settings
from .models import AgentDailyStats, AgentSession, AgentStatusLog, CallRecord, QueueDailyStats, SyncedDay
from .parsing import parse_datetime, parse_duration
from .threecx import ThreeCXClient, ThreeCXError
from .timeutil import day_bounds_utc, merged_seconds, utcnow

log = logging.getLogger(__name__)

# Calls still finishing at midnight can land in the log a little later.
COMPLETE_GRACE = timedelta(minutes=10)


@dataclass
class DayStats:
    day: date
    synced_at: datetime
    agents: dict[str, dict] = field(default_factory=dict)
    queues: dict[str, dict] = field(default_factory=dict)
    # Agents whose login session was still open when the stats were synced.
    open_sessions: set[str] = field(default_factory=set)


def empty_agent(name: str = "") -> dict:
    return {"name": name, "inbound": 0, "outbound": 0, "missed": 0, "unanswered_slow": 0,
            "talk_seconds": 0.0, "work_seconds": 0.0}


def extension_counts(rows: list[dict]) -> dict[str, dict]:
    agents: dict[str, dict] = {}
    for row in rows:
        ext = str(row.get("Dn") or "")
        if not ext:
            continue
        a = agents.setdefault(ext, empty_agent(row.get("DisplayName") or ""))
        a["inbound"] += int(row.get("InboundAnsweredCount") or 0)
        a["missed"] += int(row.get("InboundUnansweredCount") or 0)
        a["outbound"] += int(row.get("OutboundAnsweredCount") or 0) + int(row.get("OutboundUnansweredCount") or 0)
        a["talk_seconds"] += (parse_duration(row.get("InboundAnsweredTalkingDur"))
                              + parse_duration(row.get("OutboundAnsweredTalkingDur")))
    return agents


def queue_counts(rows: list[dict]) -> dict[str, dict]:
    queues: dict[str, dict] = {}
    for row in rows:
        number = str(row.get("QueueDn") or "")
        if not number:
            continue
        q = queues.setdefault(number, {"name": row.get("QueueDisplayName") or "", "received": 0, "answered": 0})
        # Received is a queue total (repeated if rows are per agent); answered is per agent.
        q["received"] = max(q["received"], int(row.get("QueueReceivedCount") or 0))
        q["answered"] += int(row.get("ExtensionAnsweredCount") or 0)
    for q in queues.values():
        q["missed"] = max(q["received"] - q["answered"], 0)
    return queues


def parse_call_record(row: dict, day: date) -> dict:
    def text(key: str, size: int) -> str:
        return str(row.get(key) or "")[:size]

    return {
        "day": day,
        "call_id": text("CallId", 64),
        "segment_id": row.get("SegmentId"),
        "indent": int(row.get("Indent") or 0),
        "start_time": parse_datetime(row.get("StartTime")),
        "source_dn": text("SourceDn", 64),
        "source_name": str(row.get("SourceDisplayName") or row.get("SourceCallerId") or "")[:200],
        "destination_dn": text("DestinationDn", 64),
        "destination_name": str(row.get("DestinationDisplayName") or row.get("DestinationCallerId") or "")[:200],
        "action_dn": text("ActionDnDn", 64),
        "action_name": text("ActionDnDisplayName", 200),
        "answered": bool(row.get("Answered")),
        "ringing_seconds": parse_duration(row.get("RingingDuration")),
        "talking_seconds": parse_duration(row.get("TalkingDuration")),
        "reason": text("Reason", 200),
        "raw": row,
    }


def slow_answer_counts(records: list[dict], extensions: set[str], threshold: float) -> Counter:
    """Calls per agent that rang longer than `threshold` seconds (answered late or not at all).

    A call log entry has a main row plus one sub-row per leg (queue -> agent); legs are
    used when present so that queue waiting time is not counted as agent ringing time.
    Each agent is counted at most once per call.
    """
    by_call: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        by_call[r["call_id"] or f"segment-{r['segment_id']}"].append(r)
    counts: Counter = Counter()
    for rows in by_call.values():
        legs = [r for r in rows if r["indent"] > 0] or rows
        counts.update({
            r["destination_dn"] for r in legs
            if r["destination_dn"] in extensions
            and r["source_dn"] != r["destination_dn"]
            and r["ringing_seconds"] > threshold
        })
    return counts


def parse_sessions(rows: list[dict]) -> list[tuple[str, str, datetime, datetime | None]]:
    sessions = []
    for row in rows:
        ext = str(row.get("AgentNo") or "")
        logged_in = parse_datetime(row.get("LoggedInDt"))
        if ext and logged_in:
            sessions.append((ext, str(row.get("QueueNo") or ""), logged_in, parse_datetime(row.get("LoggedOutDt"))))
    return sessions


def work_seconds(sessions, day_start: datetime, day_end: datetime, now: datetime) -> tuple[dict[str, float], set[str]]:
    """Logged-in seconds per agent within the day, plus agents with a session still open."""
    by_ext: dict[str, list] = defaultdict(list)
    open_now: set[str] = set()
    for ext, _queue, start, end in sessions:
        if end is None or end > now:
            if start <= now < day_end:
                open_now.add(ext)
            end = now
        by_ext[ext].append((start, end))
    window_end = min(day_end, now)
    return {ext: merged_seconds(iv, day_start, window_end) for ext, iv in by_ext.items()}, open_now


async def status_log_sessions(session: AsyncSession, start: datetime, end: datetime):
    """Logged-in intervals recorded by the poller (used when 3CX login history is unavailable)."""
    rows = (await session.execute(
        select(AgentStatusLog).where(
            AgentStatusLog.kind != "logoff",
            AgentStatusLog.started_at < end,
            or_(AgentStatusLog.ended_at.is_(None), AgentStatusLog.ended_at > start),
        )
    )).scalars()
    return [(r.extension, "", r.started_at, r.ended_at) for r in rows]


async def sync_day(client: ThreeCXClient, sessionmaker: async_sessionmaker, settings: Settings, day: date,
                   queue_numbers: list[str], now: datetime | None = None) -> DayStats:
    """Fetch one local day from 3CX and replace that day's rows in Postgres."""
    now = now or utcnow()
    start, end = day_bounds_utc(day, settings.tz)
    ext_rows, queue_rows, log_rows = await asyncio.gather(
        client.extension_statistics(start, end),
        client.queue_performance_totals(start, end, queue_numbers),
        client.call_log(start, end),
    )
    try:
        login_rows = await client.agent_login_history(start, end, settings.timezone, queue_numbers)
    except ThreeCXError as exc:
        log.warning("Agent login history unavailable for %s, using wallboard status log: %s", day, exc)
        login_rows = None

    agents = extension_counts(ext_rows)
    queues = queue_counts(queue_rows)
    records = [parse_call_record(r, day) for r in log_rows]
    for ext, count in slow_answer_counts(records, set(agents), settings.slow_answer_seconds).items():
        agents[ext]["unanswered_slow"] = count

    async with sessionmaker() as session, session.begin():
        if login_rows is not None:
            sessions = parse_sessions(login_rows)
        else:
            sessions = await status_log_sessions(session, start, end)
        work, open_now = work_seconds(sessions, start, end, now)
        for ext, seconds in work.items():
            agents.setdefault(ext, empty_agent())["work_seconds"] = seconds

        for model in (AgentDailyStats, QueueDailyStats, CallRecord, AgentSession):
            await session.execute(delete(model).where(model.day == day))
        if agents:
            await session.execute(pg_insert(AgentDailyStats), [{"day": day, "extension": ext, **a} for ext, a in agents.items()])
        if queues:
            await session.execute(pg_insert(QueueDailyStats), [{"day": day, "queue": q, **v} for q, v in queues.items()])
        if records:
            await session.execute(pg_insert(CallRecord), records)
        if login_rows is not None and sessions:
            await session.execute(pg_insert(AgentSession), [
                {"day": day, "extension": e, "queue": q, "logged_in_at": s, "logged_out_at": o}
                for e, q, s, o in sessions
            ])
        complete = login_rows is not None and now >= end + COMPLETE_GRACE
        stmt = pg_insert(SyncedDay).values(day=day, synced_at=now, complete=complete)
        await session.execute(stmt.on_conflict_do_update(
            index_elements=[SyncedDay.day], set_={"synced_at": now, "complete": complete}))

    log.info("Synced %s: %d agents, %d queues, %d call log rows", day, len(agents), len(queues), len(records))
    return DayStats(day=day, synced_at=now, agents=agents, queues=queues, open_sessions=open_now)


async def incomplete_days(sessionmaker: async_sessionmaker, days: list[date]) -> list[date]:
    async with sessionmaker() as session:
        done = set((await session.execute(
            select(SyncedDay.day).where(SyncedDay.day.in_(days), SyncedDay.complete.is_(True))
        )).scalars())
    return [d for d in days if d not in done]
