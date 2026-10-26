"""Check every 3CX endpoint the wallboard uses and save sample responses.

    cd backend && python -m scripts.probe_3cx            # local
    docker compose run --rm backend python -m scripts.probe_3cx

Writes probe-output/<endpoint>.json so field names and values can be checked
against what the wallboard expects.
"""

import asyncio
import json
import sys
from pathlib import Path

from app.config import get_settings
from app.threecx import ThreeCXClient, ThreeCXError
from app.timeutil import day_bounds_utc, local_today

OUT = Path("probe-output")


async def main() -> int:
    settings = get_settings()
    client = ThreeCXClient(settings.threecx_base_url, settings.threecx_client_id,
                           settings.threecx_client_secret, settings.threecx_verify_ssl)
    OUT.mkdir(exist_ok=True)
    start, end = day_bounds_utc(local_today(settings.tz), settings.tz)
    print(f"3CX: {settings.threecx_base_url}  today: {start:%Y-%m-%d %H:%M}Z .. {end:%Y-%m-%d %H:%M}Z")

    try:
        await client._get_token()
        print("OK    token")
    except ThreeCXError as exc:
        print(f"FAIL  token: {exc}")
        return 1

    failed = 0
    live = {}
    for name, call in {"users": client.list_users, "queues": client.list_queues,
                       "active_calls": client.active_calls}.items():
        live[name] = await run(name, call)
        failed += live[name] is None
    queue_dns = [str(q["Number"]) for q in live["queues"] or []
                 if not settings.queue_filter or str(q["Number"]) in settings.queue_filter]
    reports = {
        "extension_statistics": lambda: client.extension_statistics(start, end),
        "queue_performance_totals": lambda: client.queue_performance_totals(start, end, queue_dns),
        "agent_login_history": lambda: client.agent_login_history(start, end, settings.timezone, queue_dns),
        "call_log": lambda: client.call_log(start, end),
    }
    for name, call in reports.items():
        failed += await run(name, call) is None
    await client.close()
    print(f"\nSamples saved in {OUT.resolve()}")
    return 1 if failed else 0


async def run(name, call) -> list[dict] | None:
    try:
        rows = await call()
    except ThreeCXError as exc:
        print(f"FAIL  {name}: {exc}")
        return None
    (OUT / f"{name}.json").write_text(json.dumps(rows[:50], indent=2, ensure_ascii=False, default=str))
    fields = sorted(rows[0]) if rows else []
    print(f"OK    {name}: {len(rows)} rows  fields={fields}")
    return rows


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
