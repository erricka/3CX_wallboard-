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
from app.threecx import API, ThreeCXClient, ThreeCXError, odata_args
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
    end = day_bounds_utc(today, settings.tz)[1]
    week_start = day_bounds_utc(today - timedelta(days=6), settings.tz)[0]
    agents = sorted({str(a["Number"]) for q in queues for a in q.get("Agents") or [] if a.get("Number")})

    async def count(path: str) -> str:
        try:
            return f"{len(await client.get_all(path))} rows"
        except ThreeCXError as exc:
            return f"error {exc.status}: {str(exc).split(': ', 1)[-1][:120]}"

    print("\nQueues:")
    for q in queues:
        members = ", ".join(str(a.get("Number")) for a in q.get("Agents") or [])
        print(f"  {q['Number']} {q.get('Name')}: agents {members}")

    dates = odata_args(periodFrom=week_start, periodTo=end)
    fn = f"{API}/ReportExtensionStatistics/Pbx.GetExtensionStatisticsData"
    candidates = [(f"'{agents[0]}'" if agents else None, "one agent"),
                  (odata_args(x=",".join(agents)).split("=", 1)[1], "comma list (encoded)"),
                  ("'" + ",".join(agents) + "'", "comma list (plain)"),
                  ("'*'", "*"), ("'all'", "all")]
    print("\nExtension statistics, last 7 days, by extensionFilter (callArea=0):")
    for value, label in candidates:
        if value:
            print(f"  {label:>22}: {await count(f'{fn}({dates},extensionFilter={value},callArea=0)')}")

    print("\nAgent login history, last 7 / 30 days (all queues):")
    for days in (7, 30):
        since = day_bounds_utc(today - timedelta(days=days - 1), settings.tz)[0]
        try:
            rows = await client.agent_login_history(since, end, settings.timezone)
        except ThreeCXError as exc:
            print(f"  {days:>2} days: error {exc.status}")
            continue
        open_rows = sum(1 for r in rows if not r.get("LoggedOutDt"))
        print(f"  {days:>2} days: {len(rows)} sessions, {open_rows} still open, agents {sorted({str(r.get('AgentNo')) for r in rows})}")

    print("\nCall log, last 7 days:")
    try:
        rows = await client.call_log(week_start, end)
    except ThreeCXError as exc:
        print(f"  error: {exc}")
        return
    print(f"  {len(rows)} rows")
    for name in ("Direction", "Status", "CallType", "Indent"):
        print(f"  {name}: {dict(Counter(str(r.get(name)) for r in rows).most_common(8))}")
    involved = Counter(str(r.get(k)) for r in rows for k in ("SourceDn", "DestinationDn") if str(r.get(k)) in agents)
    print(f"  rows involving queue agents: {dict(involved)}")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
