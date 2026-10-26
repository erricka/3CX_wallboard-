"""Calls every 3CX endpoint the wallboard uses and reports what came back."""

from .config import Settings
from .threecx import ThreeCXClient, ThreeCXError
from .timeutil import day_bounds_utc, local_today

# Report functions, so a failure can be shown next to this PBX's own definition of it.
FUNCTIONS = {
    "extension_statistics": "Pbx.GetExtensionStatisticsData",
    "queue_performance_totals": "Pbx.GetQueuePerformanceTotalsData",
    "agent_login_history": "Pbx.GetAgentLoginHistoryData",
    "call_log": "Pbx.GetCallLogData",
}


def swagger_definition(swagger: str, function: str, max_lines: int = 80) -> str | None:
    """The block of swagger.yaml describing one function path (its parameters and types)."""
    lines = swagger.splitlines()
    for i, line in enumerate(lines):
        if f"/{function}(" in line and line.rstrip().endswith(":"):
            indent = len(line) - len(line.lstrip())
            block = [line]
            for nxt in lines[i + 1:i + max_lines]:
                if nxt.strip() and len(nxt) - len(nxt.lstrip()) <= indent:
                    break
                block.append(nxt)
            return "\n".join(block)
    return None


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

    failed = [r for r in results if not r["ok"] and r["check"] in FUNCTIONS]
    if failed:
        try:
            swagger = await client.swagger()
        except ThreeCXError as exc:
            swagger = None
            for r in failed:
                r["pbx_definition"] = f"swagger.yaml unavailable: {exc}"
        if swagger is not None:
            for r in failed:
                r["pbx_definition"] = swagger_definition(swagger, FUNCTIONS[r["check"]]) or "not found in swagger.yaml"
    return results, samples
