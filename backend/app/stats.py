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
Per day, every call on the PBX: totals by direction, answered, missed, talk and wait time (call log)
"""

import asyncio
import logging
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import delete, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .config import Settings
from .models import (AgentDailyStats, AgentSession, AgentStatusLog, CallRecord, Meta, OverallDailyStats,
                     QueueDailyStats, SyncedDay)
from .parsing import parse_datetime, parse_duration
from .threecx import ThreeCXClient, ThreeCXError
from .timeutil import day_bounds_utc, merged_seconds, utcnow

log = logging.getLogger(__name__)

# Calls still finishing at midnight can land in the log a little later.
COMPLETE_GRACE = timedelta(minutes=10)
# Login history lists sessions by when they started; agents often stay logged in for days.
LOGIN_LOOKBACK = timedelta(days=7)
# Bump when the way daily stats are worked out changes: days stored by an older version are fetched again.
STATS_VERSION = 4


@dataclass
class DayStats:
    day: date
    synced_at: datetime
    agents: dict[str, dict] = field(default_factory=dict)
    queues: dict[str, dict] = field(default_factory=dict)
    # Agents whose login session was still open when the stats were synced.
    open_sessions: set[str] = field(default_factory=set)
    # Every call on the PBX (overall_counts); None when the call log could not be read.
    overall: dict | None = None


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

    # v20 sets Answered on a queue that played hold music to a caller nobody took; Status says "Unanswered".
    status = str(row.get("Status") or "").lower()

    return {
        "day": day,
        # v20 numbers every row CallId 1; MainCallHistoryId is what ties the rows of one call together.
        "call_id": str(row.get("MainCallHistoryId") or row.get("CallHistoryId") or row.get("CallId") or "")[:64],
        "segment_id": row.get("SegmentId"),
        "indent": int(row.get("Indent") or 0),
        "start_time": parse_datetime(row.get("StartTime")),
        "source_dn": text("SourceDn", 64),
        "source_name": str(row.get("SourceDisplayName") or row.get("SourceCallerId") or "")[:200],
        "destination_dn": text("DestinationDn", 64),
        "destination_name": str(row.get("DestinationDisplayName") or row.get("DestinationCallerId") or "")[:200],
        "action_dn": text("ActionDnDn", 64),
        "action_name": text("ActionDnDisplayName", 200),
        "answered": status == "answered" if status else bool(row.get("Answered")),
        "ringing_seconds": parse_duration(row.get("RingingDuration")),
        "talking_seconds": parse_duration(row.get("TalkingDuration")),
        "reason": text("Reason", 200),
        "raw": row,
    }


def slow_answer_counts(records: list[dict], extensions: set[str], threshold: float) -> Counter:
    """Calls per agent that rang longer than `threshold` seconds (answered late or not at all).

    A call log entry has a main row plus one sub-row per leg (queue -> agent); legs are
    used when present so that queue waiting time is not counted as agent ringing time.
    Each agent is counted at most once per call, and only for inbound calls.
    """
    counts: Counter = Counter()
    for rows in _calls(records):
        if _direction(rows) in ("internal", "outbound"):
            continue  # only callers waiting for an agent count, like the inbound and missed columns
        legs = [r for r in rows if r["indent"] > 0] or rows
        counts.update({
            r["destination_dn"] for r in legs
            if r["destination_dn"] in extensions
            and r["source_dn"] != r["destination_dn"]
            and r["ringing_seconds"] > threshold
        })
    return counts


# Call log rows answered by a person: an extension, or the outside party of an outbound call. Voicemail,
# call scripts and IVRs are "System"; queues and ring groups only pass the call on.
PERSON_CALL_TYPES = {"extension", "external"}
# Rows that put a caller through to people: when none of them is answered, the caller was missed.
RINGING_CALL_TYPES = {"extension", "queue", "ring group"}


def _call_type(r: dict) -> str:
    return str((r.get("raw") or {}).get("CallType") or "").lower()


def _talked(r: dict) -> bool:
    """A person answered this row (not voicemail or an IVR). Builds without CallType count every answer."""
    return r["answered"] and (_call_type(r) or "extension") in PERSON_CALL_TYPES


def _calls(records: list[dict]) -> list[list[dict]]:
    by_call: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        by_call[r["call_id"] or f"segment-{r['segment_id']}"].append(r)
    return list(by_call.values())


def _direction(rows: list[dict]) -> str | None:
    """Call direction from v20's call log ("Inbound", "Outbound", "Internal"), if the build reports it."""
    for r in rows:
        value = (r.get("raw") or {}).get("Direction")
        if value:
            return str(value).lower()
    return None


def call_log_counts(records: list[dict], agent_exts: set[str], queue_numbers: list[str],
                    staff_exts: set[str] = frozenset()) -> tuple[dict[str, dict], dict[str, dict]]:
    """Agent and queue counts worked out from the call log.

    Used when this PBX's ReportExtensionStatistics / ReportQueuePerformanceTotals
    functions fail. For an inbound call, an agent whose leg was answered gets an inbound
    call and an agent who was rung but did not answer gets a missed call; an outbound
    call counts for the agent who placed it. Internal calls only add talk time. Builds
    without a Direction field fall back to telling these apart by the numbers involved.

    queue_numbers may hold queues and ring groups: every call that touched one counts as
    received there, and as answered when any extension of the PBX (staff_exts, or the
    wallboard's agents) picked it up, e.g. a ring group call taken over by a colleague.
    """
    staff = set(staff_exts) | agent_exts
    agents: dict[str, dict] = {}
    queues = {q: {"name": "", "received": 0, "answered": 0} for q in queue_numbers}
    for rows in _calls(records):
        main = next((r for r in rows if r["indent"] == 0), rows[0])
        legs = [r for r in rows if r["indent"] > 0] or rows
        direction = _direction(rows)
        answered_by = {r["destination_dn"] for r in legs if _talked(r) and r["destination_dn"] in agent_exts}
        if direction in (None, "inbound"):
            rung = {r["destination_dn"] for r in legs
                    if r["destination_dn"] in agent_exts and r["source_dn"] not in agent_exts}
            for ext in rung:
                agents.setdefault(ext, empty_agent())["inbound" if ext in answered_by else "missed"] += 1
        caller, callee = main["source_dn"], main["destination_dn"]
        placed = direction == "outbound" if direction else callee not in agent_exts and callee not in queues
        if caller in agent_exts and placed:
            agents.setdefault(caller, empty_agent())["outbound"] += 1
        for r in legs:
            if _talked(r):
                for ext in {r["source_dn"], r["destination_dn"]} & agent_exts:
                    agents.setdefault(ext, empty_agent())["talk_seconds"] += r["talking_seconds"]
        picked_up = any(_talked(r) and r["destination_dn"] in staff for r in rows)
        for q in {r[k] for r in rows for k in ("source_dn", "destination_dn", "action_dn")} & set(queues):
            queues[q]["received"] += 1
            queues[q]["answered"] += picked_up
    for q in queues.values():
        q["missed"] = max(q["received"] - q["answered"], 0)
    return agents, queues


def empty_overall() -> dict:
    return {"total": 0, "inbound": 0, "outbound": 0, "internal": 0, "inbound_answered": 0, "inbound_missed": 0,
            "outbound_answered": 0, "internal_answered": 0, "talk_seconds": 0.0, "wait_seconds": 0.0,
            "max_wait_seconds": 0.0}


def overall_counts(records: list[dict], internal_numbers: set[str] = frozenset()) -> dict:
    """Every call on the PBX that day, whoever took part.

    total = inbound + outbound + internal. An inbound call is answered when a person picked it up
    and missed when it rang an extension, queue or ring group but nobody did (an IVR or voicemail
    taking it counts as neither). Talk time adds up the answered calls' conversations; wait time is
    how long an answered inbound caller waited until a person picked up. internal_numbers (the PBX's
    extensions, queues and ring groups) tell the directions apart on builds without a Direction field.
    """
    o = empty_overall()
    for rows in _calls(records):
        direction = _direction(rows)
        if direction is None:
            main = next((r for r in rows if r["indent"] == 0), rows[0])
            if main["source_dn"] not in internal_numbers:
                direction = "inbound"
            else:
                direction = "internal" if main["destination_dn"] in internal_numbers else "outbound"
        direction = direction if direction in ("inbound", "outbound") else "internal"
        o["total"] += 1
        o[direction] += 1
        talked = [r for r in rows if _talked(r)]
        if not talked:
            if direction == "inbound" and any((_call_type(r) or "extension") in RINGING_CALL_TYPES for r in rows):
                o["inbound_missed"] += 1
            continue
        o[f"{direction}_answered"] += 1
        o["talk_seconds"] += sum(r["talking_seconds"] for r in talked)
        starts = [r["start_time"] for r in rows if r["start_time"]]
        picked = [r["start_time"] + timedelta(seconds=r["ringing_seconds"]) for r in talked if r["start_time"]]
        if direction == "inbound" and starts and picked:
            wait = max((min(picked) - min(starts)).total_seconds(), 0.0)
            o["wait_seconds"] += wait
            o["max_wait_seconds"] = max(o["max_wait_seconds"], wait)
    return o


def parse_sessions(rows: list[dict]) -> list[tuple[str, str, datetime, datetime | None]]:
    sessions = []
    for row in rows:
        ext = str(row.get("AgentNo") or "")
        logged_in = parse_datetime(row.get("LoggedInDt") or row.get("loggedInDt"))  # v20 spells it loggedInDt
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
                   queue_numbers: list[str], agent_exts: set[str], now: datetime | None = None,
                   staff_exts: set[str] = frozenset()) -> DayStats:
    """Fetch one local day from 3CX and replace that day's rows in Postgres.

    queue_numbers are the queues and ring groups on the wallboard, agent_exts their members,
    staff_exts every extension on the PBX.
    """
    now = now or utcnow()
    start, end = day_bounds_utc(day, settings.tz)
    sources = {
        "extension statistics": client.extension_statistics(start, end),
        "queue performance": client.queue_performance_totals(start, end),
        "call log": client.call_log(start, end),
        "agent login history": client.agent_login_history(start - LOGIN_LOOKBACK, end, settings.timezone),
    }
    fetched = dict(zip(sources, await asyncio.gather(*sources.values(), return_exceptions=True)))
    problems = []
    for name, result in fetched.items():
        if isinstance(result, ThreeCXError):
            problems.append(f"{name}: {result}")
            fetched[name] = None
        elif isinstance(result, BaseException):
            raise result
    ext_rows, queue_rows, log_rows, login_rows = fetched.values()
    if log_rows is None and (ext_rows is None or queue_rows is None):
        raise ThreeCXError("; ".join(problems))
    if problems:
        log.warning("3CX report problems for %s (falling back to the call log / status log): %s",
                    day, "; ".join(problems))

    records = [parse_call_record(r, day) for r in log_rows or []]
    derived_agents, derived_queues = call_log_counts(records, agent_exts, queue_numbers, staff_exts)
    agents = extension_counts(ext_rows) if ext_rows is not None else derived_agents
    # Ring groups (and queues the report leaves out) are counted from the call log; the queue
    # report only covers queues and drops its count fields when a queue had no calls.
    queues = derived_queues
    names = {str(r.get("QueueDn")): r.get("QueueDisplayName") or "" for r in queue_rows or []}
    for q, v in queues.items():
        v["name"] = names.get(q, v["name"])
    if queue_rows and any("QueueReceivedCount" in r for r in queue_rows):
        queues.update({q: v for q, v in queue_counts(queue_rows).items() if not queue_numbers or q in queue_numbers})
    overall = overall_counts(records, set(staff_exts) | agent_exts | set(queue_numbers)) if log_rows is not None else None
    slow = slow_answer_counts(records, agent_exts | set(agents), settings.slow_answer_seconds)
    for ext, count in slow.items():
        agents.setdefault(ext, empty_agent())["unanswered_slow"] = count

    async with sessionmaker() as session, session.begin():
        if login_rows is not None:
            sessions = [x for x in parse_sessions(login_rows) if not x[1] or not queue_numbers or x[1] in queue_numbers]
            # Ring group members have no queue login; use the time the wallboard saw them online.
            with_login = {x[0] for x in sessions}
            online = [x for x in await status_log_sessions(session, start, end)
                      if x[0] in agent_exts and x[0] not in with_login]
        else:
            sessions, online = await status_log_sessions(session, start, end), []
        work, open_now = work_seconds(sessions + online, start, end, now)
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
        if overall is not None:  # without a call log, keep the last overall counts stored for the day
            await session.execute(delete(OverallDailyStats).where(OverallDailyStats.day == day))
            await session.execute(pg_insert(OverallDailyStats), [{"day": day, **overall}])
        if login_rows is not None and sessions:
            await session.execute(pg_insert(AgentSession), [
                {"day": day, "extension": e, "queue": q, "logged_in_at": s, "logged_out_at": o}
                for e, q, s, o in sessions
            ])
        # Counts derived from a complete call log are final too, so only those two sources matter.
        complete = log_rows is not None and login_rows is not None and now >= end + COMPLETE_GRACE
        stmt = pg_insert(SyncedDay).values(day=day, synced_at=now, complete=complete)
        await session.execute(stmt.on_conflict_do_update(
            index_elements=[SyncedDay.day], set_={"synced_at": now, "complete": complete}))

    log.info("Synced %s: %d agents, %d queues, %d call log rows", day, len(agents), len(queues), len(records))
    return DayStats(day=day, synced_at=now, agents=agents, queues=queues, open_sessions=open_now, overall=overall)


async def incomplete_days(sessionmaker: async_sessionmaker, days: list[date]) -> list[date]:
    async with sessionmaker() as session:
        done = set((await session.execute(
            select(SyncedDay.day).where(SyncedDay.day.in_(days), SyncedDay.complete.is_(True))
        )).scalars())
    return [d for d in days if d not in done]


async def refetch_if_outdated(sessionmaker: async_sessionmaker) -> bool:
    """Mark every stored day for a fresh fetch when it was worked out by an older STATS_VERSION."""
    async with sessionmaker() as session, session.begin():
        stored = await session.get(Meta, "stats_version")
        if stored and stored.value == str(STATS_VERSION):
            return False
        await session.execute(update(SyncedDay).values(complete=False))
        await session.merge(Meta(key="stats_version", value=str(STATS_VERSION)))
    log.info("Daily stats rules changed (version %s): stored days will be fetched from 3CX again", STATS_VERSION)
    return True
