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
    assert snap["queues"] == [{"number": "800", "name": "Inbound", "kind": "queue", "agents_in_work": 4, "agents_free": 1,
                               "agents_talk": 1, "calls_waiting": 1, "max_wait_seconds": 42,
                               "answered": 104, "missed": 14, "answer_rate": 88}]


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


async def test_extension_statistics_finds_working_arguments():
    import httpx

    from app.threecx import ThreeCXClient

    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/connect/token":
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        calls.append(request.url.path)
        if "callArea=1" not in request.url.path:  # this PBX only accepts callArea=1
            return httpx.Response(500)
        return httpx.Response(200, json={"value": [{"Dn": "101"}]})

    client = ThreeCXClient("https://pbx.example", "id", "secret", transport=httpx.MockTransport(handler))
    start = datetime(2026, 10, 25, 17, tzinfo=UTC)
    assert await client.extension_statistics(start, start + timedelta(days=1)) == [{"Dn": "101"}]
    assert "extensionFilter='',callArea=1" in calls[-1] and len(calls) == 3
    await client.extension_statistics(start, start + timedelta(days=1))
    assert len(calls) == 4  # remembered: straight to the working arguments
    assert "extensionFilter=null" in odata_args(extensionFilter=None)
    await client.close()


def test_call_log_counts_uses_direction_field():
    from app.stats import call_log_counts

    day = date(2026, 10, 26)
    rows = [  # v20 builds: every row Indent 1, with Direction / Status
        {"CallId": "1", "SegmentId": 1, "Indent": 1, "Direction": "Internal", "SourceDn": "1001", "DestinationDn": "1002",
         "Answered": True, "TalkingDuration": "PT10S"},
        {"CallId": "2", "SegmentId": 2, "Indent": 1, "Direction": "Inbound", "SourceDn": "+85512", "DestinationDn": "1002",
         "Answered": False, "Status": "Unanswered"},
        {"CallId": "3", "SegmentId": 3, "Indent": 1, "Direction": "Outbound", "SourceDn": "1001", "DestinationDn": "+85598",
         "Answered": True, "TalkingDuration": "PT20S"},
    ]
    agents, _ = call_log_counts([parse_call_record(r, day) for r in rows], {"1001", "1002"}, ["9910"])
    assert (agents["1001"]["inbound"], agents["1001"]["outbound"], agents["1001"]["missed"]) == (0, 1, 0)
    assert (agents["1002"]["inbound"], agents["1002"]["outbound"], agents["1002"]["missed"]) == (0, 0, 1)
    assert agents["1001"]["talk_seconds"] == 30 and agents["1002"]["talk_seconds"] == 10


async def test_concurrent_401s_refresh_the_token_once():
    import asyncio

    import httpx

    from app.threecx import ThreeCXClient

    issued = []  # like this PBX: a new token cancels the previous one

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/connect/token":
            issued.append(f"t{len(issued) + 1}")
            return httpx.Response(200, json={"access_token": issued[-1], "expires_in": 3600})
        await asyncio.sleep(0.01)
        if request.headers["Authorization"] != f"Bearer {issued[-1]}":
            return httpx.Response(401)
        return httpx.Response(200, json={"value": []})

    client = ThreeCXClient("https://pbx.example", "id", "secret", transport=httpx.MockTransport(handler))
    await client.get("/xapi/v1/Users")
    issued.append("t-other")  # another program logged in with the same API client
    await asyncio.gather(client.get("/xapi/v1/Users"), client.get("/xapi/v1/ActiveCalls"))
    assert issued == ["t1", "t-other", "t3"]
    await client.close()


def test_range_days():
    from app.timeutil import MAX_RANGE_DAYS, range_days

    now = datetime(2026, 10, 26, 3, tzinfo=UTC)  # 10:00 in Phnom Penh
    days = range_days(date(2026, 6, 1), date(2026, 10, 10), TZ, now)
    assert days[0] == date(2026, 6, 1) and days[-1] == date(2026, 10, 10) and len(days) == 132
    assert range_days(date(2026, 10, 26), date(2026, 10, 26), TZ, now) == [date(2026, 10, 26)]
    for start, end, message in [
        (None, date(2026, 10, 1), "start date and an end date"),
        (date(2026, 10, 5), date(2026, 10, 1), "on or before the end date"),
        (date(2026, 10, 1), date(2026, 10, 27), "cannot be in the future"),
        (date(2025, 1, 1), date(2026, 10, 1), f"at most {MAX_RANGE_DAYS} days"),
    ]:
        with pytest.raises(ValueError, match=message):
            range_days(start, end, TZ, now)


def test_report_endpoint_rejects_bad_date_ranges():
    from fastapi.testclient import TestClient

    from app.config import Settings
    from app.main import create_app

    settings = Settings(threecx_client_id="", threecx_client_secret="",
                        database_url="postgresql+asyncpg://x:y@127.0.0.1:9/none")
    with TestClient(create_app(settings)) as client:
        def detail(query):
            res = client.get(f"/api/reports/daily?{query}")
            return res.status_code, res.json()["detail"]

        assert detail("period=range") == (400, "Choose a start date and an end date for the date range.")
        assert detail("period=range&start=2026-10-10&end=2026-06-01") == (
            400, "The start date must be on or before the end date.")
        assert detail("period=range&start=2026-06-01&end=2999-01-01") == (400, "The end date cannot be in the future.")
        assert detail("period=range&start=2026-06-01&end=2026-10-10")[0] == 503  # valid; database not up here
        assert client.get("/api/reports/daily?period=range&start=june&end=2026-10-10").status_code == 422


def test_real_v20_shapes_callid_always_1_and_lowercase_login_field():
    """Shapes seen on the real PBX: every row CallId/SegmentId 1, calls told apart by MainCallHistoryId,
    login history with 'loggedInDt'."""
    from app.stats import call_log_counts, parse_sessions

    day = date(2026, 10, 26)
    rows = [
        {"CallId": 1, "SegmentId": 1, "Indent": 1, "MainCallHistoryId": "call-a", "Direction": "Outbound",
         "SourceDn": "0360", "DestinationDn": "10000", "Answered": False, "TalkingDuration": "PT0S"},
        {"CallId": 1, "SegmentId": 1, "Indent": 1, "MainCallHistoryId": "call-b", "Direction": "Outbound",
         "SourceDn": "0360", "DestinationDn": "10000", "Answered": True, "TalkingDuration": "PT8M"},
        {"CallId": 1, "SegmentId": 1, "Indent": 1, "MainCallHistoryId": "call-c", "Direction": "Inbound",
         "SourceDn": "10000", "DestinationDn": "0360", "Answered": True, "TalkingDuration": "PT1M"},
    ]
    records = [parse_call_record(r, day) for r in rows]
    assert [r["call_id"] for r in records] == ["call-a", "call-b", "call-c"]
    agents, _ = call_log_counts(records, {"0360"}, ["9910"])
    assert (agents["0360"]["outbound"], agents["0360"]["inbound"], agents["0360"]["talk_seconds"]) == (2, 1, 540)

    sessions = parse_sessions([{"AgentNo": "0521", "QueueNo": "9910", "loggedInDt": "2026-10-26T07:29:25Z",
                                "LoggedOutDt": "2026-10-26T11:26:32Z"}])
    assert sessions == [("0521", "9910", datetime(2026, 10, 26, 7, 29, 25, tzinfo=UTC),
                         datetime(2026, 10, 26, 11, 26, 32, tzinfo=UTC))]


def test_ring_group_members_use_phone_status_not_queue_login():
    now = datetime(2026, 10, 26, 3, tzinfo=UTC)
    users = [
        # in ring group 8001 only: logged out of queues, but the phone is online -> Ready
        {"Number": "0360", "FirstName": "Chhuon", "LastName": "Danet", "QueueStatus": "LoggedOut", "IsRegistered": True},
        {"Number": "0366", "FirstName": "Sak", "LastName": "K", "QueueStatus": "LoggedOut", "IsRegistered": False},
        {"Number": "0367", "FirstName": "Thea", "LastName": "S", "QueueStatus": "LoggedIn", "IsRegistered": True},
        # in queue 9910: queue login still decides
        {"Number": "0521", "FirstName": "Po", "LastName": "Sam Nang", "QueueStatus": "LoggedOut", "IsRegistered": True},
    ]
    groups = [
        {"Number": "9910", "Name": "QUE1", "kind": "queue", "Agents": [{"Number": "0521"}]},
        {"Number": "8001", "Name": "MaxBIT-CallIN(PRO)", "kind": "ring_group",
         "Agents": [{"Number": "0360"}, {"Number": "0366"}, {"Number": "0367"}]},
    ]
    calls = [{"Caller": "+85570", "Callee": "0367 Thea S", "Status": "Talking"}]
    stats = DayStats(day=date(2026, 10, 26), synced_at=now, queues={"8001": {"received": 9, "answered": 7, "missed": 2}})
    snap = build_snapshot(users, groups, calls, stats, now, TZ, [])

    status = {a["extension"]: (a["status"], a["logged_in"]) for a in snap["agents"]}
    assert status == {"0360": ("Ready", True), "0366": ("Offline", False), "0367": ("Talking", True),
                      "0521": ("Logoff", False)}
    ring = next(q for q in snap["queues"] if q["number"] == "8001")
    assert (ring["kind"], ring["agents_in_work"], ring["agents_free"], ring["agents_talk"]) == ("ring_group", 2, 1, 1)
    assert (ring["answered"], ring["missed"]) == (7, 2)


def test_ring_group_call_taken_over_by_a_colleague_counts_as_answered():
    from app.stats import call_log_counts

    day = date(2026, 10, 26)
    rows = [  # real shape: ring group 8001 hunts 0367, the call is picked up by 0322 (not a member)
        {"MainCallHistoryId": "c1", "Indent": 1, "Direction": "Inbound", "SourceDn": "10000", "DestinationDn": "8001",
         "Answered": False, "Status": "Redirected"},
        {"MainCallHistoryId": "c1", "Indent": 1, "Direction": "Inbound", "SourceDn": "10000", "DestinationDn": "0367",
         "Answered": False, "RingingDuration": "PT9S"},
        {"MainCallHistoryId": "c1", "Indent": 1, "Direction": "Inbound", "SourceDn": "10000", "DestinationDn": "0322",
         "Answered": True, "TalkingDuration": "PT23S"},
        # nobody picked up
        {"MainCallHistoryId": "c2", "Indent": 1, "Direction": "Inbound", "SourceDn": "10000", "DestinationDn": "8001",
         "Answered": False, "Status": "Unanswered"},
    ]
    records = [parse_call_record(r, day) for r in rows]
    agents, groups = call_log_counts(records, {"0360", "0366", "0367"}, ["8001"], staff_exts={"0322", "0367"})
    assert groups["8001"] == {"name": "", "received": 2, "answered": 1, "missed": 1}
    assert agents["0367"]["missed"] == 1


async def test_only_ring_group_8001_titled_inbound_queue(tmp_path, monkeypatch):
    from app.config import Settings
    from app.service import WallboardService

    env = tmp_path / ".env"
    env.write_text("WALLBOARD_QUEUES=none\nWALLBOARD_RING_GROUPS=8001\nWALLBOARD_GROUP_NAMES=8001=Inbound Queue\n")
    monkeypatch.chdir(tmp_path)
    for var in ("WALLBOARD_QUEUES", "WALLBOARD_RING_GROUPS", "WALLBOARD_GROUP_NAMES"):
        monkeypatch.delenv(var, raising=False)
    settings = Settings(_env_file=str(env))
    assert (settings.hide_queues, settings.queue_filter, settings.group_names) == (True, [], {"8001": "Inbound Queue"})

    class PBX:
        async def list_queues(self):
            raise AssertionError("queues are hidden, so they are not even fetched")

        async def list_ring_groups(self):
            return [{"Number": "8000", "Name": "Maxbit", "Members": [{"Number": "0322"}]},
                    {"Number": "8001", "Name": "MaxBIT-CallIN(PRO)", "Members": [{"Number": "0360"}, {"Number": "0367"}]}]

    service = WallboardService(settings, PBX(), sessionmaker=None)
    service._queues = await service._load_groups()
    assert [(g["Number"], g["Name"], g["kind"]) for g in service._queues] == [("8001", "Inbound Queue", "ring_group")]
    assert service.queue_numbers() == ["8001"] and service.agent_numbers() == {"0360", "0367"}


def _real_call(cid, start, direction, call_type, src, dst, status, ring="PT0S", talk="PT0S"):
    """One call log row in the shape the real v20 PBX returns."""
    return {"MainCallHistoryId": cid, "Indent": 1, "StartTime": start, "Direction": direction, "CallType": call_type,
            "SourceDn": src, "DestinationDn": dst, "Status": status, "Answered": status == "Answered",
            "RingingDuration": ring, "TalkingDuration": talk}


def test_overall_counts_every_call_on_the_pbx():
    from app.stats import call_log_counts, overall_counts
    from app.wallboard import overall_row

    day = date(2026, 10, 28)
    rows = [
        # inbound via ring group 8001: 0366 picks up after 5 s, talks 20 s
        _real_call("in-1", "2026-10-28T09:06:20.0Z", "Inbound", "Ring Group", "10000", "8001", "Redirected", "PT5S"),
        _real_call("in-1", "2026-10-28T09:06:20.1Z", "Inbound", "Extension", "10000", "0366", "Answered", "PT4.9S", "PT20S"),
        # inbound, 0322 takes over from 0367 after 3 s, then transfers to a call script (System: not talk time)
        _real_call("in-2", "2026-10-28T07:41:26.9Z", "Inbound", "Ring Group", "10000", "8001", "Redirected", "PT3S"),
        _real_call("in-2", "2026-10-28T07:41:27.0Z", "Inbound", "Extension", "10000", "0367", "Unanswered", "PT3S"),
        _real_call("in-2", "2026-10-28T07:41:29.9Z", "Inbound", "Extension", "10000", "0322", "Answered", "PT0S", "PT40S"),
        _real_call("in-2", "2026-10-28T07:42:10.0Z", "Inbound", "System", "10000", "6010", "Answered", "PT0.2S", "PT15S"),
        # inbound, nobody in ring group 8001 picks up
        _real_call("in-3", "2026-10-28T04:23:00Z", "Inbound", "Ring Group", "10000", "8001", "Unanswered", "PT0.1S"),
        # inbound to 0360, busy, goes to voicemail: missed (voicemail is not an answer)
        _real_call("in-4", "2026-10-28T09:30:52.6Z", "Inbound", "Extension", "10011", "0360", "Unanswered", "PT0.1S"),
        _real_call("in-4", "2026-10-28T09:30:52.7Z", "Inbound", "System", "10011", "0360", "Answered", "PT0.2S", "PT2M"),
        # outbound: one answered (60 s), one not
        _real_call("out-1", "2026-10-28T08:16:31Z", "Outbound", "External", "1521", "10000", "Answered", "PT1S", "PT1M"),
        _real_call("out-2", "2026-10-28T04:15:52Z", "Outbound", "External", "1521", "10000", "Unanswered", "PT13S"),
        # internal: a colleague answers (40 s); a queue plays hold music for 30 s and nobody takes it
        _real_call("int-1", "2026-10-28T02:41:49Z", "Internal", "Extension", "0322", "0524", "Answered", "PT3S", "PT40S"),
        {**_real_call("int-2", "2026-10-27T03:06:07Z", "Internal", "Queue", "0521", "8004", "Unanswered",
                      "PT0.1S", "PT30S"), "Answered": True},
    ]
    records = [parse_call_record(r, day) for r in rows]
    o = overall_counts(records)
    assert (o["total"], o["inbound"], o["outbound"], o["internal"]) == (8, 4, 2, 2)
    assert (o["inbound_answered"], o["inbound_missed"], o["outbound_answered"], o["internal_answered"]) == (2, 2, 1, 1)
    assert o["talk_seconds"] == pytest.approx(20 + 40 + 60 + 40)  # no call script, voicemail or hold music
    assert o["wait_seconds"] == pytest.approx(5 + 3) and o["max_wait_seconds"] == pytest.approx(5)

    row = overall_row(o, calls=[{"Caller": "0322 Sovan", "Callee": "0524 Vireakboth", "Status": "Talking"}])
    assert row["answer_rate"] == 50 and row["avg_talk_seconds"] == 40 and row["avg_wait_seconds"] == 4
    assert row["calls_now"] == 1 and row["total_calls"] == 8

    # The same rules for agents and the ring group: voicemail is a missed call, hold music no talk time.
    agents, groups = call_log_counts(records, {"0360", "0366", "0367"}, ["8001"], staff_exts={"0322", "0360", "0521"})
    assert (agents["0360"]["inbound"], agents["0360"]["missed"], agents["0360"]["talk_seconds"]) == (0, 1, 0)
    assert (agents["0366"]["inbound"], agents["0366"]["talk_seconds"]) == (1, 20)
    assert groups["8001"] == {"name": "", "received": 3, "answered": 2, "missed": 1}


def test_overall_directions_without_a_direction_field():
    from app.stats import overall_counts

    day = date(2026, 10, 28)
    rows = [{"MainCallHistoryId": cid, "Indent": 0, "SourceDn": src, "DestinationDn": dst, "Answered": True,
             "TalkingDuration": "PT10S"} for cid, src, dst in
            [("a", "+855", "101"), ("b", "101", "+855"), ("c", "101", "102"), ("d", "101", "800")]]
    o = overall_counts([parse_call_record(r, day) for r in rows], {"101", "102", "800"})
    assert (o["inbound"], o["outbound"], o["internal"], o["talk_seconds"]) == (1, 1, 2, 40)
