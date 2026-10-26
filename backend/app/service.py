"""Background loops: live polling of 3CX, stats sync to Postgres, and WebSocket fan-out."""

import asyncio
import logging
import time
from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import func, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import async_sessionmaker

from .config import Settings
from .models import Agent, AgentStatusLog, Queue
from .stats import DayStats, incomplete_days, refetch_if_outdated, sync_day
from .threecx import ThreeCXClient, ThreeCXError
from .timeutil import local_today, utcnow
from .wallboard import build_snapshot, user_name

log = logging.getLogger(__name__)

QUEUE_REFRESH_SECONDS = 60


class WallboardService:
    def __init__(self, settings: Settings, client: ThreeCXClient, sessionmaker: async_sessionmaker):
        self.settings = settings
        self.client = client
        self.sessionmaker = sessionmaker
        self.snapshot: dict | None = None
        self._subscribers: set[asyncio.Queue] = set()
        self._users: list[dict] = []
        self._queues: list[dict] = []
        self._queues_fetched = 0.0
        self._directory_ready = asyncio.Event()
        self._today: DayStats | None = None
        self._stats_error: str | None = None
        self._statuses: dict[str, str] = {}
        self._day_locks: dict[date, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._tasks: list[asyncio.Task] = []
        self.db_ready = False

    # ---- lifecycle --------------------------------------------------------------

    def start(self, prepare_db) -> None:
        """Start background work. The web server is already serving while the database comes up."""
        self._tasks = [asyncio.create_task(self._run(prepare_db))]

    async def _run(self, prepare_db) -> None:
        while True:
            try:
                await prepare_db()
                break
            except Exception as exc:
                log.warning("Database not ready: %s", exc)
                self._publish_error(f"Waiting for the PostgreSQL database: {exc}")
                await asyncio.sleep(3)
        async with self.sessionmaker() as session, session.begin():
            # Rows left open by a previous run end when that run was last seen.
            await session.execute(
                update(AgentStatusLog).where(AgentStatusLog.ended_at.is_(None))
                .values(ended_at=func.coalesce(AgentStatusLog.last_seen_at, AgentStatusLog.started_at)))
        await refetch_if_outdated(self.sessionmaker)
        self.db_ready = True
        await asyncio.gather(self._poll_loop(), self._stats_loop())

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    # ---- subscribers ------------------------------------------------------------

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=1)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)

    def _publish(self, snapshot: dict) -> None:
        self.snapshot = snapshot
        for queue in self._subscribers:
            if queue.full():
                queue.get_nowait()  # slow client: keep only the newest snapshot
            queue.put_nowait(snapshot)

    # ---- live polling -----------------------------------------------------------

    def queue_numbers(self) -> list[str]:
        """Queues and ring groups shown on the wallboard."""
        numbers = [str(q["Number"]) for q in self._queues]
        return numbers or self.settings.queue_filter + self.settings.ring_group_filter

    def agent_numbers(self) -> set[str]:
        return {str(a["Number"]) for q in self._queues for a in q.get("Agents") or [] if a.get("Number")}

    def staff_numbers(self) -> set[str]:
        return {str(u["Number"]) for u in self._users if u.get("Number")}

    async def _load_groups(self) -> list[dict]:
        """Queues (all, or WALLBOARD_QUEUES) plus the ring groups in WALLBOARD_RING_GROUPS."""
        wanted_queues, wanted_groups = self.settings.queue_filter, self.settings.ring_group_filter
        queues = [{**q, "kind": "queue"} for q in await self.client.list_queues()
                  if q.get("Number") and (not wanted_queues or str(q["Number"]) in wanted_queues)]
        if not wanted_groups:
            return queues
        groups = {str(g["Number"]): g for g in await self.client.list_ring_groups() if g.get("Number")}
        missing = [n for n in wanted_groups if n not in groups]
        if missing:
            log.warning("Ring groups not found on the PBX: %s", ", ".join(missing))
        return queues + [{"Number": n, "Name": groups[n].get("Name") or n, "Agents": groups[n].get("Members") or [],
                          "kind": "ring_group"} for n in wanted_groups if n in groups]

    async def _poll_loop(self) -> None:
        interval = self.settings.poll_interval_seconds
        while True:
            started = time.monotonic()
            try:
                await self.poll_once()
            except Exception as exc:  # keep polling through 3CX/network hiccups
                log.warning("Wallboard poll failed: %s", exc)
                self._publish_error(f"Cannot load data from 3CX: {exc}")
            await asyncio.sleep(max(interval - (time.monotonic() - started), 0.5))

    async def poll_once(self) -> None:
        self._users, calls = await asyncio.gather(self.client.list_users(), self.client.active_calls())
        if not self._directory_ready.is_set() or time.monotonic() - self._queues_fetched > QUEUE_REFRESH_SECONDS:
            self._queues = await self._load_groups()
            self._queues_fetched = time.monotonic()
            await self._save_directory()
            self._directory_ready.set()

        now = utcnow()
        today = local_today(self.settings.tz, now)
        day_stats = self._today if self._today and self._today.day == today else None
        snapshot = build_snapshot(self._users, self._queues, calls, day_stats, now, self.settings.tz, [])
        snapshot["slow_answer_seconds"] = self.settings.slow_answer_seconds
        if self._stats_error:
            snapshot["errors"].append(f"Daily counters could not be refreshed: {self._stats_error}")
        await self._record_statuses(snapshot["agents"], now)
        self._publish(snapshot)

    def _publish_error(self, message: str) -> None:
        base = dict(self.snapshot) if self.snapshot else {"queues": [], "agents": [], "generated_at": None}
        base["errors"] = [message]
        base["stale"] = True
        self._publish(base)

    async def _save_directory(self) -> None:
        async with self.sessionmaker() as session, session.begin():
            agents = [{"extension": str(u["Number"]), "name": user_name(u)} for u in self._users if u.get("Number")]
            if agents:
                stmt = pg_insert(Agent)
                await session.execute(stmt.on_conflict_do_update(
                    index_elements=[Agent.extension], set_={"name": stmt.excluded.name, "updated_at": func.now()}),
                    agents)
            queues = [{
                "number": str(q["Number"]),
                "name": q.get("Name") or "",
                "agent_extensions": sorted({str(a["Number"]) for a in q.get("Agents") or [] if a.get("Number")}),
            } for q in self._queues if q.get("Number")]
            if queues:
                stmt = pg_insert(Queue)
                await session.execute(stmt.on_conflict_do_update(
                    index_elements=[Queue.number],
                    set_={"name": stmt.excluded.name, "agent_extensions": stmt.excluded.agent_extensions,
                          "updated_at": func.now()}),
                    queues)

    async def _record_statuses(self, agents: list[dict], now: datetime) -> None:
        changed = [a for a in agents if self._statuses.get(a["extension"]) != a["status"]]
        if not changed:
            return
        async with self.sessionmaker() as session, session.begin():
            exts = [a["extension"] for a in changed]
            await session.execute(update(AgentStatusLog).where(
                AgentStatusLog.extension.in_(exts), AgentStatusLog.ended_at.is_(None)).values(ended_at=now))
            session.add_all(AgentStatusLog(extension=a["extension"], status=a["status"], kind=a["kind"],
                                           started_at=now, last_seen_at=now) for a in changed)
        self._statuses.update({a["extension"]: a["status"] for a in changed})

    # ---- daily stats ------------------------------------------------------------

    async def _stats_loop(self) -> None:
        await self._directory_ready.wait()
        backfilled = False
        while True:
            try:
                await self.refresh_today()
                self._stats_error = None
            except Exception as exc:
                log.warning("Daily stats sync failed: %s", exc)
                self._stats_error = str(exc)
            if not backfilled:
                await self._backfill()
                backfilled = True
            await asyncio.sleep(self.settings.stats_refresh_seconds)

    async def refresh_today(self) -> None:
        async with self.sessionmaker() as session, session.begin():
            await session.execute(update(AgentStatusLog).where(AgentStatusLog.ended_at.is_(None))
                                  .values(last_seen_at=utcnow()))
        today = local_today(self.settings.tz)
        await self.sync(today)
        # Finalise yesterday once after midnight so its report rows are complete.
        for day in await incomplete_days(self.sessionmaker, [today - timedelta(days=1)]):
            await self.sync(day)

    async def _backfill(self) -> None:
        today = local_today(self.settings.tz)
        days = [today - timedelta(days=i) for i in range(self.settings.backfill_days, 0, -1)]
        for day in await incomplete_days(self.sessionmaker, days):
            try:
                await self.sync(day)
            except Exception as exc:
                log.warning("Backfill of %s failed: %s", day, exc)

    async def sync(self, day: date) -> DayStats:
        async with self._day_locks[day]:
            stats = await sync_day(self.client, self.sessionmaker, self.settings, day, self.queue_numbers(),
                                   self.agent_numbers(), staff_exts=self.staff_numbers())
        if day == local_today(self.settings.tz):
            self._today = stats
        return stats

    async def ensure_synced(self, days: list[date]) -> list[str]:
        """Pull any days a report needs that are not stored yet. Returns warnings for failed days."""
        todo = await incomplete_days(self.sessionmaker, days)
        today = local_today(self.settings.tz)
        if (today in todo and self._today and self._today.day == today
                and (utcnow() - self._today.synced_at).total_seconds() < self.settings.stats_refresh_seconds):
            todo.remove(today)
        warnings: list[str] = []
        limit = asyncio.Semaphore(4)

        async def one(day: date) -> None:
            async with limit:
                try:
                    await self.sync(day)
                except (ThreeCXError, OSError) as exc:
                    warnings.append(f"{day}: data could not be refreshed from 3CX ({exc})")

        await asyncio.gather(*(one(d) for d in todo))
        return sorted(warnings)
