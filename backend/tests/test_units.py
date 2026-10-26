from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.parsing import number_tokens, parse_datetime, parse_duration
from app.stats import DayStats, extension_counts, parse_call_record, queue_counts, slow_answer_counts, work_seconds
from app.threecx import odata_args
from app.timeutil import day_bounds_utc, merged_seconds, period_days
from app.wallboard import build_snapshot

TZ = ZoneInfo("Asia/Phnom_Penh")
UTC = timezone.utc


@pytest.mark.parametrize("value,expected", [
    ("PT1M5.5S", 65.5), ("PT2H", 7200), ("P1DT1S", 86401), ("PT0S", 0),
    ("00:01:05", 65), ("1.00:00:10", 86410), (None, 0), ("", 0), (12, 12), ("garbage", 0),
])
def test_parse_duration(value, expected):
    assert parse_duration(value) == expected


def test_parse_datetime_handles_z_long_fractions_and_naive():
    assert parse_datetime("2026-10-26T01:02:03.1234567Z") == datetime(2026, 10, 26, 1, 2, 3, 123456, UTC)
    assert parse_datetime("2026-10-26T01:02:03").tzinfo == UTC
    assert parse_datetime(None) is None


def test_number_tokens():
    assert number_tokens("Inbound (800)") == {"800"}
    assert number_tokens("107 Iv Sophanith") == {"107"}
    assert number_tokens(None) == set()


def test_odata_args_quotes_and_encodes():
    args = odata_args(periodFrom=datetime(2026, 10, 25, 17, tzinfo=UTC), queueDns="800,801",
                      clientTimeZone="Asia/Phnom_Penh", callArea=0, hidePcalls=True, name="O'Neil")
    assert args == ("periodFrom=2026-10-25T17:00:00.000Z,queueDns='800%2C801',clientTimeZone='Asia%2FPhnom_Penh',"
                    "callArea=0,hidePcalls=true,name='O%27%27Neil'")


def test_day_bounds_and_periods():
    start, end = day_bounds_utc(date(2026, 10, 26), TZ)
    assert start == datetime(2026, 10, 25, 17, tzinfo=UTC) and end - start == timedelta(days=1)
    now = datetime(2026, 10, 26, 3, tzinfo=UTC)
    assert period_days("today", TZ, now) == [date(2026, 10, 26)]
    assert period_days("yesterday", TZ, now) == [date(2026, 10, 25)]
    assert period_days("7days", TZ, now)[0] == date(2026, 10, 20)
    assert len(period_days("1month", TZ, now)) == 30
    with pytest.raises(ValueError):
        period_days("week", TZ, now)


def test_merged_seconds_counts_overlaps_once_and_clips():
    t = datetime(2026, 10, 26, 8, tzinfo=UTC)
    h = timedelta(hours=1)
    intervals = [(t, t + 2 * h), (t + h, t + 3 * h), (t + 5 * h, t + 6 * h), (t - 2 * h, t - h)]
    assert merged_seconds(intervals, t, t + 10 * h) == 4 * 3600


def test_extension_and_queue_counts():
    agents = extension_counts([{"Dn": "101", "DisplayName": "A", "InboundAnsweredCount": 3, "InboundUnansweredCount": 1,
                                "OutboundAnsweredCount": 2, "OutboundUnansweredCount": 1,
                                "InboundAnsweredTalkingDur": "PT1M", "OutboundAnsweredTalkingDur": "PT30S"}])
    assert agents["101"] | {} == {"name": "A", "inbound": 3, "outbound": 3, "missed": 1, "unanswered_slow": 0,
                                  "talk_seconds": 90.0, "work_seconds": 0.0}
    # per-agent rows repeat the queue's received total
    queues = queue_counts([
        {"QueueDn": "800", "QueueReceivedCount": 10, "ExtensionAnsweredCount": 4},
        {"QueueDn": "800", "QueueReceivedCount": 10, "ExtensionAnsweredCount": 5},
    ])
    assert queues["800"] == {"name": "", "received": 10, "answered": 9, "missed": 1}


def test_slow_answer_uses_legs_and_counts_once_per_call():
    day = date(2026, 10, 26)
    rows = [
        {"CallId": "1", "SegmentId": 1, "Indent": 0, "SourceDn": "+855", "DestinationDn": "103", "RingingDuration": "PT30S"},
        {"CallId": "1", "SegmentId": 2, "Indent": 1, "SourceDn": "800", "DestinationDn": "107", "RingingDuration": "PT9S"},
        {"CallId": "1", "SegmentId": 3, "Indent": 1, "SourceDn": "800", "DestinationDn": "107", "RingingDuration": "PT8S"},
        {"CallId": "1", "SegmentId": 4, "Indent": 1, "SourceDn": "800", "DestinationDn": "103", "RingingDuration": "PT2S"},
        {"CallId": "2", "SegmentId": 5, "Indent": 0, "SourceDn": "+855", "DestinationDn": "103", "RingingDuration": "PT6S"},
    ]
    records = [parse_call_record(r, day) for r in rows]
    assert slow_answer_counts(records, {"103", "107"}, 5) == {"107": 1, "103": 1}


def test_work_seconds_open_session_runs_to_now():
    start, end = day_bounds_utc(date(2026, 10, 26), TZ)
    now = start + timedelta(hours=10)
    sessions = [("103", "800", start + timedelta(hours=1), start + timedelta(hours=3)),
                ("103", "801", start + timedelta(hours=2), None),
                ("107", "800", start - timedelta(hours=2), start + timedelta(hours=1))]
    work, open_now = work_seconds(sessions, start, end, now)
    assert work == {"103": 9 * 3600, "107": 3600}
    assert open_now == {"103"}


def test_build_snapshot_statuses_and_queue_counters():
    now = datetime(2026, 10, 26, 3, tzinfo=UTC)
    users = [
        {"Number": "101", "FirstName": "Bonthoeun", "LastName": "Soth", "QueueStatus": "LoggedOut", "IsRegistered": True},
        {"Number": "103", "FirstName": "Doum", "LastName": "Ratana", "QueueStatus": "LoggedIn", "IsRegistered": True,
         "CurrentProfileName": "Available"},
        {"Number": "104", "FirstName": "Hang", "LastName": "S", "QueueStatus": "LoggedIn", "IsRegistered": True,
         "CurrentProfileName": "Away"},
        {"Number": "107", "FirstName": "Iv", "LastName": "Sophanith", "QueueStatus": "LoggedIn", "IsRegistered": True},
        {"Number": "110", "FirstName": "Mao", "LastName": "Sokha", "QueueStatus": "LoggedIn", "IsRegistered": True},
    ]
    queues = [{"Number": "800", "Name": "Inbound", "Agents": [{"Number": n} for n in ("101", "103", "104", "107", "110")]},
              {"Number": "900", "Name": "Other", "Agents": []}]
    calls = [
        {"Caller": "+85512", "Callee": "107 Iv Sophanith", "Status": "Talking"},
        {"Caller": "+85598", "Callee": "Inbound (800)", "Status": "Routing",
         "LastChangeStatus": "2026-10-26T02:59:18Z", "ServerNow": "2026-10-26T03:00:00Z"},
        {"Caller": "+85570", "Callee": "110 Mao Sokha", "Status": "Ringing"},
    ]
    stats = DayStats(day=date(2026, 10, 26), synced_at=now - timedelta(seconds=30),
                     agents={"103": {"name": "", "inbound": 7, "outbound": 0, "missed": 0, "unanswered_slow": 4,
                                     "talk_seconds": 100, "work_seconds": 2160}},
                     queues={"800": {"received": 118, "answered": 104, "missed": 14}}, open_sessions={"103"})
    snap = build_snapshot(users, queues, calls, stats, now, TZ, ["800"])

    by_ext = {a["extension"]: a for a in snap["agents"]}
    assert {e: a["status"] for e, a in by_ext.items()} == {
        "101": "Logoff", "103": "Ready", "104": "Away", "107": "Talking", "110": "Ringing"}
    assert by_ext["103"]["inbound"] == 7 and by_ext["103"]["unanswered_slow"] == 4
    assert by_ext["103"]["work_seconds"] == 2160 + 30
    assert [a["name"] for a in snap["agents"]][0] == "Bonthoeun Soth"
    assert snap["queues"] == [{"number": "800", "name": "Inbound", "agents_in_work": 4, "agents_free": 1,
                               "agents_talk": 1, "calls_waiting": 1, "max_wait_seconds": 42,
                               "answered": 104, "missed": 14}]


async def test_client_adapts_to_3cx_top_limit_and_keeps_queue_status():
    import httpx

    from app.threecx import ThreeCXClient

    users = [{"Number": str(100 + i)} for i in range(250)]
    selects = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/connect/token":
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        top, skip = int(request.url.params["$top"]), int(request.url.params["$skip"])
        selects.append(request.url.params["$select"])
        if top > 100:  # what the PBX returned
            return httpx.Response(400, json={"error": {"code": "", "message":
                "The query specified in the URI is not valid. The limit of '100' for Top query has been exceeded. "
                f"The value from the incoming request is '{top}'.", "details": []}})
        return httpx.Response(200, json={"value": users[skip:skip + top]})

    client = ThreeCXClient("https://pbx.example", "id", "secret", transport=httpx.MockTransport(handler))
    assert await client.list_users() == users
    assert all("QueueStatus" in s for s in selects)
    await client.list_users()
    assert len(selects) == 1 + 3 + 3  # one refused request, then 100-row pages only
    await client.close()


def test_call_log_counts_fallback():
    from app.stats import call_log_counts

    day = date(2026, 10, 26)
    rows = [
        # queue call: 103 rang without answering, 107 answered
        {"CallId": "1", "SegmentId": 1, "Indent": 0, "SourceDn": "+855", "DestinationDn": "107", "ActionDnDn": "800",
         "Answered": True},
        {"CallId": "1", "SegmentId": 2, "Indent": 1, "SourceDn": "800", "DestinationDn": "103", "Answered": False},
        {"CallId": "1", "SegmentId": 3, "Indent": 1, "SourceDn": "800", "DestinationDn": "107", "Answered": True,
         "TalkingDuration": "PT2M"},
        # abandoned in queue
        {"CallId": "2", "SegmentId": 4, "Indent": 0, "SourceDn": "+855", "DestinationDn": "800", "Answered": False},
        # outbound call by 103, and an internal call 103 -> 107 that is neither
        {"CallId": "3", "SegmentId": 5, "Indent": 0, "SourceDn": "103", "DestinationDn": "+85512", "Answered": True,
         "TalkingDuration": "PT30S"},
        {"CallId": "4", "SegmentId": 6, "Indent": 0, "SourceDn": "103", "DestinationDn": "107", "Answered": True},
    ]
    agents, queues = call_log_counts([parse_call_record(r, day) for r in rows], {"103", "107"}, ["800"])
    assert (agents["107"]["inbound"], agents["107"]["missed"], agents["107"]["talk_seconds"]) == (1, 0, 120)
    assert (agents["103"]["inbound"], agents["103"]["missed"], agents["103"]["outbound"]) == (0, 1, 1)
    assert agents["103"]["talk_seconds"] == 30
    assert queues["800"] == {"name": "", "received": 2, "answered": 1, "missed": 1}
