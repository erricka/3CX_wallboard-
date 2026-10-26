"""Async client for the 3CX v20 Configuration API (XAPI).

Auth is OAuth2 client credentials: POST /connect/token with the Client ID and API key
created under Admin Console > Integrations > API (enable "XAPI Access").
Report functions take their filters as OData function arguments inside the path,
e.g. /xapi/v1/ReportCallLogData/Pbx.GetCallLogData(periodFrom=...,periodTo=...,...).
"""

import asyncio
import logging
import time
from datetime import datetime, timezone
from urllib.parse import quote

import httpx

log = logging.getLogger(__name__)

API = "/xapi/v1"
USER_FIELDS = ["Id", "Number", "FirstName", "LastName", "CurrentProfileName", "IsRegistered", "QueueStatus"]


class ThreeCXError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def odata_args(**kwargs) -> str:
    """Render OData function arguments: dates unquoted UTC, strings quoted and URL-encoded."""
    parts = []
    for key, value in kwargs.items():
        if isinstance(value, bool):
            rendered = "true" if value else "false"
        elif isinstance(value, int):
            rendered = str(value)
        elif isinstance(value, datetime):
            rendered = value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        else:
            rendered = "'" + quote(str(value).replace("'", "''"), safe="") + "'"
        parts.append(f"{key}={rendered}")
    return ",".join(parts)


class ThreeCXClient:
    def __init__(self, base_url: str, client_id: str, client_secret: str, verify_ssl: bool = True,
                 timeout: float = 30, transport: httpx.AsyncBaseTransport | None = None):
        self._client_id = client_id
        self._client_secret = client_secret
        self._http = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout,
                                       verify=verify_ssl, transport=transport)
        self._token: str | None = None
        self._token_expiry = 0.0
        self._token_lock = asyncio.Lock()
        self._user_fields = list(USER_FIELDS)

    async def close(self) -> None:
        await self._http.aclose()

    async def _get_token(self, force: bool = False) -> str:
        async with self._token_lock:
            if not force and self._token and time.monotonic() < self._token_expiry:
                return self._token
            if not self._client_id or not self._client_secret:
                raise ThreeCXError("3CX API credentials are not set (THREECX_CLIENT_ID / THREECX_CLIENT_SECRET)")
            try:
                resp = await self._http.post("/connect/token", data={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "grant_type": "client_credentials",
                })
            except httpx.HTTPError as exc:
                raise ThreeCXError(f"Cannot reach 3CX: {exc}") from exc
            if resp.status_code != 200:
                raise ThreeCXError(f"3CX token request failed ({resp.status_code}): {resp.text[:200]}",
                                   resp.status_code)
            body = resp.json()
            self._token = body["access_token"]
            expires_in = float(body.get("expires_in") or 60)
            self._token_expiry = time.monotonic() + max(expires_in - 10, 30)
            return self._token

    async def get(self, path: str, params: dict | None = None) -> dict:
        for attempt in range(2):
            token = await self._get_token(force=attempt > 0)
            try:
                resp = await self._http.get(path, params=params, headers={"Authorization": f"Bearer {token}"})
            except httpx.HTTPError as exc:
                raise ThreeCXError(f"Cannot reach 3CX: {exc}") from exc
            if resp.status_code == 401 and attempt == 0:
                continue
            if resp.status_code >= 400:
                raise ThreeCXError(f"GET {path} -> {resp.status_code}: {resp.text[:300]}", resp.status_code)
            return resp.json()
        raise ThreeCXError("3CX rejected the access token", 401)

    async def get_all(self, path: str, params: dict | None = None, page_size: int = 1000) -> list[dict]:
        rows: list[dict] = []
        skip = 0
        while True:
            page = await self.get(path, {**(params or {}), "$top": page_size, "$skip": skip})
            batch = page.get("value", [])
            rows.extend(batch)
            if len(batch) < page_size:
                return rows
            skip += page_size

    # ---- live state -------------------------------------------------------------

    async def list_users(self) -> list[dict]:
        try:
            return await self.get_all(f"{API}/Users", {"$select": ",".join(self._user_fields)}, page_size=500)
        except ThreeCXError as exc:
            # Older v20 builds have no QueueStatus property; $select on it returns 400.
            if exc.status == 400 and "QueueStatus" in self._user_fields:
                log.warning("Users.QueueStatus not supported by this 3CX build; using IsRegistered instead")
                self._user_fields.remove("QueueStatus")
                return await self.list_users()
            raise

    async def list_queues(self) -> list[dict]:
        return await self.get_all(f"{API}/Queues", {"$select": "Id,Number,Name", "$expand": "Agents"}, page_size=200)

    async def active_calls(self) -> list[dict]:
        return (await self.get(f"{API}/ActiveCalls")).get("value", [])

    # ---- reports (all ranges are UTC datetimes) ---------------------------------

    async def extension_statistics(self, start: datetime, end: datetime) -> list[dict]:
        args = odata_args(periodFrom=start, periodTo=end, extensionFilter="", callArea=0)
        return await self.get_all(f"{API}/ReportExtensionStatistics/Pbx.GetExtensionStatisticsData({args})")

    async def queue_performance_totals(self, start: datetime, end: datetime, queue_dns: list[str]) -> list[dict]:
        args = odata_args(periodFrom=start, periodTo=end, queueDns=",".join(queue_dns), waitInterval="0:00:00")
        return await self.get_all(f"{API}/ReportQueuePerformanceTotals/Pbx.GetQueuePerformanceTotalsData({args})")

    async def agent_login_history(self, start: datetime, end: datetime, tz_name: str,
                                  queue_dns: list[str]) -> list[dict]:
        args = odata_args(clientTimeZone=tz_name, startDt=start, endDt=end,
                          queueDnStr=",".join(queue_dns), agentDnStr="")
        return await self.get_all(f"{API}/ReportAgentLoginHistory/Pbx.GetAgentLoginHistoryData({args})")

    async def call_log(self, start: datetime, end: datetime) -> list[dict]:
        args = odata_args(periodFrom=start, periodTo=end, sourceType=0, sourceFilter="", destinationType=0,
                          destinationFilter="", callsType=0, callTimeFilterType=0,
                          callTimeFilterFrom="0:00:0", callTimeFilterTo="0:00:0", hidePcalls=True)
        return await self.get_all(f"{API}/ReportCallLogData/Pbx.GetCallLogData({args})", {"$orderby": "SegmentId"})
