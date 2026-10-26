"""Check every 3CX endpoint the wallboard uses and save sample responses.

    cd backend && python -m scripts.probe_3cx
    docker compose run --rm app python -m scripts.probe_3cx

Writes probe-output/<endpoint>.json so field names and values can be checked
against what the wallboard expects, then tries filter variants on the report
functions to see which ones return data on this PBX.
"""

import asyncio
import json
import sys
from collections import Counter
from datetime import timedelta
from pathlib import Path

from app.config import get_settings
from app.diagnostics import run_checks
from app.threecx import API, EXTENSION_STATS_VARIANTS, ThreeCXClient, ThreeCXError, odata_args
from app.timeutil import day_bounds_utc, local_today

OUT = Path("probe-output")


async def main() -> int:
    settings = get_settings()
    client = ThreeCXClient(settings.threecx_base_url, settings.threecx_client_id,
                           settings.threecx_client_secret, settings.threecx_verify_ssl)
    print(f"3CX: {settings.threecx_base_url}")
    try:
        results, samples = await run_checks(client, settings)
        OUT.mkdir(exist_ok=True)
        for name, rows in samples.items():
            (OUT / f"{name}.json").write_text(json.dumps(rows[:50], indent=2, ensure_ascii=False, default=str))
        for r in results:
            if r["ok"]:
                print(f"OK    {r['check']}: {r['rows']} rows  fields={r['fields']}")
            else:
                print(f"FAIL  {r['check']}: {r['error']}")
        print(f"\nSamples saved in {OUT.resolve()}")
        await experiments(client, settings, samples.get("queues", []))
    finally:
        await client.close()
    return 0 if all(r["ok"] for r in results) else 1


async def experiments(client: ThreeCXClient, settings, queues: list[dict]) -> None:
    today = local_today(settings.tz)
    start, end = day_bounds_utc(today, settings.tz)
    week_start = day_bounds_utc(today - timedelta(days=6), settings.tz)[0]
    numbers = [str(q["Number"]) for q in queues]

    async def count(path: str) -> str:
        try:
            return f"{len(await client.get_all(path))} rows"
        except ThreeCXError as exc:
            return f"error {exc.status}"

    print("\nQueues:")
    for q in queues:
        print(f"  {q['Number']} {q.get('Name')}: {len(q.get('Agents') or [])} agents")

    variants = [("comma list", ",".join(numbers)), ("empty", "")] + [(n, n) for n in numbers]
    print("\nQueue performance totals, last 7 days, by queueDns:")
    for label, dns in variants:
        args = odata_args(periodFrom=week_start, periodTo=end, queueDns=dns, waitInterval="0:00:00")
        print(f"  {label:>12}: {await count(f'{API}/ReportQueuePerformanceTotals/Pbx.GetQueuePerformanceTotalsData({args})')}")

    print("\nAgent login history, last 7 days, by queueDnStr:")
    for label, dns in variants:
        args = odata_args(clientTimeZone=settings.timezone, startDt=week_start, endDt=end, queueDnStr=dns, agentDnStr="")
        print(f"  {label:>12}: {await count(f'{API}/ReportAgentLoginHistory/Pbx.GetAgentLoginHistoryData({args})')}")

    print("\nExtension statistics, today, by (extensionFilter, callArea):")
    for extension_filter, call_area in EXTENSION_STATS_VARIANTS:
        args = odata_args(periodFrom=start, periodTo=end, extensionFilter=extension_filter, callArea=call_area)
        label = f"({extension_filter!r}, {call_area})"
        print(f"  {label:>12}: {await count(f'{API}/ReportExtensionStatistics/Pbx.GetExtensionStatisticsData({args})')}")

    print("\nCall log, last 7 days:")
    try:
        rows = await client.call_log(week_start, end)
    except ThreeCXError as exc:
        print(f"  error: {exc}")
        return
    print(f"  {len(rows)} rows")
    for name in ("Direction", "Status", "CallType", "ActionType", "SourceType", "DestinationType", "Indent"):
        print(f"  {name}: {dict(Counter(str(r.get(name)) for r in rows).most_common(8))}")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
