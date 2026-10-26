"""Builds the live wallboard snapshot from 3CX Users, Queues and ActiveCalls."""

from datetime import datetime
from zoneinfo import ZoneInfo

from .parsing import number_tokens, parse_datetime
from .stats import DayStats, empty_agent

READY_PROFILES = {"available"}
RINGING_STATES = {"ringing"}


def is_logged_in(user: dict) -> bool:
    """Queue login state; builds without Users.QueueStatus fall back to phone registration."""
    status = user.get("QueueStatus")
    if status is None:
        return user.get("IsRegistered") is not False
    if isinstance(status, (int, float)):
        return status == 1
    return str(status).lower() == "loggedin"


def user_name(user: dict) -> str:
    return " ".join(p for p in (user.get("FirstName"), user.get("LastName")) if p).strip()


def call_states(calls: list[dict], agent_exts: set[str], queue_numbers: set[str],
                now: datetime) -> tuple[dict[str, str], dict[str, list[float]]]:
    """Per-agent call state ("ringing"/"talking") and waiting seconds of calls sitting in each queue."""
    agent_state: dict[str, str] = {}
    waiting: dict[str, list[float]] = {}
    for call in calls:
        status = str(call.get("Status") or "").lower()
        caller = number_tokens(call.get("Caller"))
        callee = number_tokens(call.get("Callee"))
        agents = (caller | callee) & agent_exts
        if agents:
            for ext in agents:
                state = "ringing" if ext in callee and status in RINGING_STATES else "talking"
                if agent_state.get(ext) != "talking":
                    agent_state[ext] = state
            continue
        queues = callee & queue_numbers
        if queues:
            server_now = parse_datetime(call.get("ServerNow")) or now
            since = parse_datetime(call.get("LastChangeStatus")) or parse_datetime(call.get("EstablishedAt"))
            wait = max((server_now - since).total_seconds(), 0) if since else 0
            for q in queues:
                waiting.setdefault(q, []).append(wait)
    return agent_state, waiting


def agent_status(user: dict, call_state: str | None) -> tuple[str, str]:
    """(label, kind) where kind drives the colour: ready, talking, ringing, away, logoff."""
    if call_state == "ringing":
        return "Ringing", "ringing"
    if call_state == "talking":
        return "Talking", "talking"
    if not is_logged_in(user):
        return "Logoff", "logoff"
    if user.get("IsRegistered") is False:
        return "Offline", "logoff"
    profile = user.get("CurrentProfileName") or "Available"
    if profile.lower() in READY_PROFILES:
        return "Ready", "ready"
    return profile, "away"


def build_snapshot(users: list[dict], queues: list[dict], calls: list[dict], day_stats: DayStats | None,
                   now: datetime, tz: ZoneInfo, queue_filter: list[str]) -> dict:
    users_by_ext = {str(u["Number"]): u for u in users if u.get("Number")}
    shown = [q for q in queues if not queue_filter or str(q.get("Number")) in queue_filter]

    members: dict[str, set[str]] = {}
    agent_names: dict[str, str] = {}
    for q in shown:
        members[str(q["Number"])] = set()
        for a in q.get("Agents") or []:
            ext = str(a.get("Number") or "")
            if ext:
                members[str(q["Number"])].add(ext)
                agent_names.setdefault(ext, a.get("Name") or "")
    agent_exts = set().union(*members.values()) if members else set(users_by_ext)

    states, waiting = call_states(calls, agent_exts, set(members), now)
    stats_agents = day_stats.agents if day_stats else {}

    agents = []
    for ext in agent_exts:
        user = users_by_ext.get(ext, {})
        status, kind = agent_status(user, states.get(ext))
        logged_in = is_logged_in(user) and user.get("IsRegistered") is not False
        s = stats_agents.get(ext) or empty_agent()
        work = s["work_seconds"]
        if day_stats and ext in day_stats.open_sessions and logged_in:
            work += max((now - day_stats.synced_at).total_seconds(), 0)
        agents.append({
            "extension": ext,
            "name": user_name(user) or agent_names.get(ext) or s["name"] or ext,
            "status": status,
            "kind": kind,
            "logged_in": logged_in,
            "inbound": s["inbound"],
            "outbound": s["outbound"],
            "missed": s["missed"],
            "unanswered_slow": s["unanswered_slow"],
            "talk_seconds": round(s["talk_seconds"]),
            "work_seconds": round(work),
        })
    agents.sort(key=lambda a: (a["name"].casefold(), a["extension"]))

    queue_rows = []
    for q in shown:
        number = str(q["Number"])
        team = [a for a in agents if a["extension"] in members[number] and a["logged_in"]]
        waits = waiting.get(number, [])
        qs = (day_stats.queues.get(number) if day_stats else None) or {}
        queue_rows.append({
            "number": number,
            "name": q.get("Name") or number,
            "agents_in_work": len(team),
            "agents_free": sum(a["kind"] == "ready" for a in team),
            "agents_talk": sum(a["kind"] == "talking" for a in team),
            "calls_waiting": len(waits),
            "max_wait_seconds": round(max(waits, default=0)),
            "answered": qs.get("answered", 0),
            "missed": qs.get("missed", 0),
        })

    return {
        "generated_at": now.isoformat(),
        "day": now.astimezone(tz).date().isoformat(),
        "timezone": str(tz),
        "stats_synced_at": day_stats.synced_at.isoformat() if day_stats else None,
        "queues": queue_rows,
        "agents": agents,
        "errors": [],
    }
