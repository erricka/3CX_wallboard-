"""Daily report built from the stats stored in Postgres, exported as Excel or CSV."""

import csv
import io
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from zoneinfo import ZoneInfo

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Agent, AgentDailyStats, CallRecord, Queue, QueueDailyStats
from .timeutil import PERIODS

COUNT_FIELDS = ("inbound", "outbound", "missed", "unanswered_slow")
TIME_FIELDS = ("talk_seconds", "work_seconds")


@dataclass
class ReportData:
    period: str
    days: list[date]
    tz: ZoneInfo
    generated_at: datetime
    slow_seconds: int
    agents: list[tuple[str, str]] = field(default_factory=list)  # (extension, name)
    queues: list[tuple[str, str]] = field(default_factory=list)  # (number, name)
    agent_daily: dict[tuple[date, str], dict] = field(default_factory=dict)
    queue_daily: dict[tuple[date, str], dict] = field(default_factory=dict)
    calls: list[CallRecord] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def title(self) -> str:
        first, last = self.days[0], self.days[-1]
        span = first.isoformat() if first == last else f"{first.isoformat()} to {last.isoformat()}"
        return f"{PERIODS[self.period]} ({span})"

    @property
    def filename_stem(self) -> str:
        return f"3cx-daily-report_{self.days[0].isoformat()}_to_{self.days[-1].isoformat()}"

    def agent_day(self, day: date, ext: str) -> dict:
        return self.agent_daily.get((day, ext)) or {f: 0 for f in COUNT_FIELDS + TIME_FIELDS}

    def queue_day(self, day: date, number: str) -> dict:
        return self.queue_daily.get((day, number)) or {"received": 0, "answered": 0, "missed": 0}


async def load_report(session: AsyncSession, period: str, days: list[date], tz: ZoneInfo, queue_filter: list[str],
                      slow_seconds: int, now: datetime) -> ReportData:
    data = ReportData(period=period, days=days, tz=tz, generated_at=now, slow_seconds=slow_seconds)

    queue_stmt = select(Queue).order_by(Queue.number)
    if queue_filter:
        queue_stmt = queue_stmt.where(Queue.number.in_(queue_filter))
    queues = (await session.execute(queue_stmt)).scalars().all()
    data.queues = [(q.number, q.name) for q in queues]

    names = dict((await session.execute(select(Agent.extension, Agent.name))).all())
    agent_exts = set().union(*(q.agent_extensions or [] for q in queues)) if queues else set(names)

    for row in (await session.execute(select(AgentDailyStats).where(
            AgentDailyStats.day.in_(days), AgentDailyStats.extension.in_(agent_exts)))).scalars():
        data.agent_daily[(row.day, row.extension)] = {f: getattr(row, f) for f in COUNT_FIELDS + TIME_FIELDS}
        names.setdefault(row.extension, row.name)
    data.agents = sorted(((e, names.get(e) or e) for e in agent_exts), key=lambda a: (a[1].casefold(), a[0]))

    queue_numbers = [n for n, _ in data.queues]
    for row in (await session.execute(select(QueueDailyStats).where(
            QueueDailyStats.day.in_(days), QueueDailyStats.queue.in_(queue_numbers)))).scalars():
        data.queue_daily[(row.day, row.queue)] = {"received": row.received, "answered": row.answered,
                                                   "missed": row.missed}

    # Call log: main rows of every call that touched one of the report's agents or queues.
    involved = agent_exts | set(queue_numbers)
    by_call: dict[str, list[CallRecord]] = defaultdict(list)
    for rec in (await session.execute(select(CallRecord).where(CallRecord.day.in_(days))
                                      .order_by(CallRecord.start_time, CallRecord.segment_id))).scalars():
        by_call[rec.call_id or f"segment-{rec.segment_id}"].append(rec)
    for rows in by_call.values():
        if any({r.source_dn, r.destination_dn, r.action_dn} & involved for r in rows):
            data.calls.extend(r for r in rows if r.indent == 0)
    data.calls.sort(key=lambda r: (r.start_time or now, r.segment_id or 0))
    return data


def _totals(rows: list[dict], fields) -> dict:
    return {f: sum(r[f] for r in rows) for f in fields}


def _rate(answered: int, received: int) -> float | None:
    return answered / received if received else None


def _hms(seconds: float) -> str:
    seconds = int(round(seconds))
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


# ---- Excel ---------------------------------------------------------------------

HEADER_FILL = PatternFill("solid", fgColor="D9E1EC")
THIN = Side(style="thin", color="A6B1C2")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
TIME_FORMAT = "[h]:mm:ss"


def _write_table(ws, start_row: int, headers: list[str], rows: list[list], formats: dict[int, str] | None = None) -> int:
    """Write a bordered table; returns the next free row."""
    for col, title in enumerate(headers, 1):
        cell = ws.cell(row=start_row, column=col, value=title)
        cell.font = Font(bold=True)
        cell.fill = HEADER_FILL
        cell.border = BORDER
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for r, values in enumerate(rows, start_row + 1):
        for col, value in enumerate(values, 1):
            cell = ws.cell(row=r, column=col, value=value)
            cell.border = BORDER
            if formats and col in formats:
                cell.number_format = formats[col]
            if col > 1 and not isinstance(value, str):
                cell.alignment = Alignment(horizontal="center")
    return start_row + len(rows) + 1


def _autosize(ws, minimum: int = 10, maximum: int = 40) -> None:
    widths: dict[int, int] = defaultdict(int)
    for row in ws.iter_rows():
        for cell in row:
            if cell.value is not None and not (cell.row <= 3 and cell.column == 1):
                widths[cell.column] = max(widths[cell.column], len(str(cell.value)))
    for col, width in widths.items():
        ws.column_dimensions[get_column_letter(col)].width = min(max(width + 2, minimum), maximum)


def to_xlsx(data: ReportData) -> bytes:
    wb = Workbook()
    slow = f"Unanswered within {data.slow_seconds} sec"
    agent_headers = ["Inbound calls", "Outbound calls", "Missed calls", slow, "Talk time", "Work time"]

    # Summary
    ws = wb.active
    ws.title = "Summary"
    ws["A1"] = "3CX Call Center Daily Report"
    ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = f"Period: {data.title}"
    ws["A3"] = f"Generated: {data.generated_at.astimezone(data.tz):%Y-%m-%d %H:%M} ({data.tz})"
    row = 5
    ws.cell(row=row, column=1, value="Queues").font = Font(bold=True, size=12)
    queue_rows = []
    for number, name in data.queues:
        t = _totals([data.queue_day(d, number) for d in data.days], ("received", "answered", "missed"))
        queue_rows.append([name, number, t["received"], t["answered"], t["missed"], _rate(t["answered"], t["received"])])
    row = _write_table(ws, row + 1, ["Queue", "Number", "Received calls", "Answered calls", "Missed calls", "Answer rate"],
                       queue_rows, {6: "0.0%"}) + 1
    ws.cell(row=row, column=1, value="Agents").font = Font(bold=True, size=12)
    agent_rows = []
    for ext, name in data.agents:
        t = _totals([data.agent_day(d, ext) for d in data.days], COUNT_FIELDS + TIME_FIELDS)
        agent_rows.append([name, ext, *(t[f] for f in COUNT_FIELDS), t["talk_seconds"] / 86400, t["work_seconds"] / 86400])
    row = _write_table(ws, row + 1, ["Agent", "Extension", *agent_headers], agent_rows,
                       {7: TIME_FORMAT, 8: TIME_FORMAT}) + 1
    if data.warnings:
        ws.cell(row=row, column=1, value="Notes").font = Font(bold=True, size=12)
        for i, warning in enumerate(data.warnings, row + 1):
            ws.cell(row=i, column=1, value=warning)
    _autosize(ws)

    # Daily agent stats (days where the agent worked or had calls)
    ws = wb.create_sheet("Daily Agents")
    rows = []
    for day in data.days:
        for ext, name in data.agents:
            s = data.agent_day(day, ext)
            if any(s[f] for f in COUNT_FIELDS + TIME_FIELDS):
                rows.append([day, name, ext, *(s[f] for f in COUNT_FIELDS), s["talk_seconds"] / 86400,
                             s["work_seconds"] / 86400])
    _write_table(ws, 1, ["Date", "Agent", "Extension", *agent_headers], rows,
                 {1: "yyyy-mm-dd", 8: TIME_FORMAT, 9: TIME_FORMAT})
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:I{len(rows) + 1}"
    _autosize(ws)

    # Daily queue stats
    ws = wb.create_sheet("Daily Queues")
    rows = []
    for day in data.days:
        for number, name in data.queues:
            s = data.queue_day(day, number)
            rows.append([day, name, number, s["received"], s["answered"], s["missed"], _rate(s["answered"], s["received"])])
    _write_table(ws, 1, ["Date", "Queue", "Number", "Received calls", "Answered calls", "Missed calls", "Answer rate"],
                 rows, {1: "yyyy-mm-dd", 7: "0.0%"})
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:G{len(rows) + 1}"
    _autosize(ws)

    # Call log
    ws = wb.create_sheet("Call Log")
    rows = []
    for c in data.calls:
        start = c.start_time.astimezone(data.tz).replace(tzinfo=None) if c.start_time else None
        rows.append([start, c.call_id, c.source_dn, c.source_name, c.destination_dn, c.destination_name,
                     c.action_name or c.action_dn, "Yes" if c.answered else "No",
                     c.ringing_seconds / 86400, c.talking_seconds / 86400, c.reason])
    _write_table(ws, 1, ["Start time", "Call ID", "From", "From name", "To", "To name", "Via", "Answered",
                         "Ringing", "Talking", "Reason"], rows,
                 {1: "yyyy-mm-dd hh:mm:ss", 9: TIME_FORMAT, 10: TIME_FORMAT})
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:K{len(rows) + 1}"
    _autosize(ws)

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


# ---- CSV -----------------------------------------------------------------------

def to_csv(data: ReportData) -> bytes:
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["3CX Call Center Daily Report", data.title])
    w.writerow([])
    w.writerow(["Date", "Agent", "Extension", "Inbound calls", "Outbound calls", "Missed calls",
                f"Unanswered within {data.slow_seconds} sec", "Talk time", "Work time"])
    for day in data.days:
        for ext, name in data.agents:
            s = data.agent_day(day, ext)
            w.writerow([day.isoformat(), name, ext, *(s[f] for f in COUNT_FIELDS),
                        _hms(s["talk_seconds"]), _hms(s["work_seconds"])])
    w.writerow([])
    w.writerow(["Date", "Queue", "Number", "Received calls", "Answered calls", "Missed calls"])
    for day in data.days:
        for number, name in data.queues:
            s = data.queue_day(day, number)
            w.writerow([day.isoformat(), name, number, s["received"], s["answered"], s["missed"]])
    for warning in data.warnings:
        w.writerow(["Note", warning])
    # BOM so Excel opens UTF-8 (Khmer names) correctly.
    return out.getvalue().encode("utf-8-sig")
