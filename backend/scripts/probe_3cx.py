"""Check every 3CX endpoint the wallboard uses and save sample responses.

    cd backend && python -m scripts.probe_3cx
    docker compose run --rm app python -m scripts.probe_3cx

Writes probe-output/<endpoint>.json so field names and values can be checked
against what the wallboard expects.
"""

import asyncio
import json
import sys
from pathlib import Path

from app.config import get_settings
from app.diagnostics import run_checks
from app.threecx import ThreeCXClient

OUT = Path("probe-output")


async def main() -> int:
    settings = get_settings()
    client = ThreeCXClient(settings.threecx_base_url, settings.threecx_client_id,
                           settings.threecx_client_secret, settings.threecx_verify_ssl)
    print(f"3CX: {settings.threecx_base_url}")
    try:
        results, samples = await run_checks(client, settings)
    finally:
        await client.close()

    OUT.mkdir(exist_ok=True)
    for name, rows in samples.items():
        (OUT / f"{name}.json").write_text(json.dumps(rows[:50], indent=2, ensure_ascii=False, default=str))
    for r in results:
        if r["ok"]:
            print(f"OK    {r['check']}: {r['rows']} rows  fields={r['fields']}")
        else:
            print(f"FAIL  {r['check']}: {r['error']}")
    print(f"\nSamples saved in {OUT.resolve()}")
    return 0 if all(r["ok"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
