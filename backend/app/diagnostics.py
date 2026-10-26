"""Calls every 3CX endpoint the wallboard uses and reports what came back."""

from .config import Settings
from .threecx import ThreeCXClient, ThreeCXError
from .timeutil import day_bounds_utc, local_today


async def run_checks(client: ThreeCXClient, settings: Settings) -> tuple[list[dict], dict[str, list[dict]]]:
    """Per-endpoint result (ok, row count, field names or error) plus the raw rows."""
    start, end = day_bounds_utc(local_today(settings.tz), settings.tz)
    results: list[dict] = []
    samples: dict[str, list[dict]] = {}

    async def check(name: str, call) -> list[dict]:
        try:
            rows = await call()
        except ThreeCXError as exc:
            results.append({"check": name, "ok": False, "error": str(exc)})
            return []
        results.append({"check": name, "ok": True, "rows": len(rows), "fields": sorted(rows[0]) if rows else []})
        samples[name] = rows
        return rows

    queues = await check("queues", client.list_queues)
    await check("users", client.list_users)
    await check("active_calls", client.active_calls)
    queue_dns = [str(q["Number"]) for q in queues
                 if not settings.queue_filter or str(q["Number"]) in settings.queue_filter]
    await check("extension_statistics", lambda: client.extension_statistics(start, end))
    await check("queue_performance_totals", lambda: client.queue_performance_totals(start, end, queue_dns))
    await check("agent_login_history",
                lambda: client.agent_login_history(start, end, settings.timezone, queue_dns))
    await check("call_log", lambda: client.call_log(start, end))
    return results, samples
