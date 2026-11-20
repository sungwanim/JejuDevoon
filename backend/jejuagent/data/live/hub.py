"""제주데이터허브 API 클라이언트. 명세: data/docs/schemas/농산물품종별*.hwpx

요청: GET https://open.jejudatahub.net/api/proxy/{API ID}/{프로젝트키}?startDate&endDate&cultivar[&period]&number&limit
응답: {totCnt, hasMore, data:[...]}. 페이지당 limit 최대 100. 키는 URL 경로에 들어가므로 예외·로그에 URL을 쓰지 않는다.
"""
from __future__ import annotations

import logging
import os

import httpx

from .errors import LiveError

log = logging.getLogger(__name__)
BASE = "https://open.jejudatahub.net/api/proxy"
KEY_ENV = "JEJU_HUB_PROJECT_KEY"
API_ID = {"daily": "13t6aat1at6166111Dtt1taa1ta1661t", "moving_avg": "0106aa36D6363Da1ttaatat3t3031a1a"}  # 제주데이터허브 API 화면의 호출 주소에 있는 API ID (비밀값 아님). 명세서(hwpx)의 ID와 달라서 허브 화면 값을 썼다
PERIODS = (1, 2, 7, 30, 90)
CULTIVARS = ["당근(일반)", "세척당근", "흙당근", "깐마늘", "마늘", "마늘(수입)", "저장형 난지", "저장형 남도", "햇마늘 남도",
             "세척무", "월동무", "양배추(수입)", "양배추(일반)", "저장양배추", "만생양파", "저장양파", "조생양파", "중만생양파"]
MAX_PAGES = 1000  # hasMore가 계속 true인 이상 응답에 대한 안전장치


class HubClient:
    def __init__(self, project_key: str | None = None, transport: httpx.BaseTransport | None = None):
        self._key = project_key if project_key is not None else os.environ.get(KEY_ENV, "")
        self._http = httpx.Client(transport=transport, timeout=30)

    def fetch(self, api: str, start: str, end: str, cultivar: str, period: int | None = None, limit: int = 100) -> list[dict]:
        """모든 페이지를 이어 붙여 행 목록을 돌려준다. api: 'daily' | 'moving_avg'. 날짜는 YYYYMMDD."""
        if not (start and end and cultivar):
            raise ValueError("startDate, endDate, cultivar는 필수입니다")
        if api == "moving_avg" and period not in PERIODS:
            raise ValueError(f"period는 {PERIODS} 중 하나여야 합니다")
        if not self._key:
            raise LiveError("no_key", KEY_ENV)
        limit = min(limit, 100)
        params = {"startDate": start, "endDate": end, "cultivar": cultivar}
        if api == "moving_avg":
            params["period"] = str(period)
        rows: list[dict] = []
        for number in range(1, MAX_PAGES + 1):
            body = self._get(api, {**params, "number": number, "limit": limit})
            rows += body.get("data", [])
            if not body.get("hasMore"):
                break
        return rows

    def _get(self, api: str, params: dict) -> dict:
        log.info("hub GET %s %s", api, {k: v for k, v in params.items()})  # URL(키 포함)은 기록하지 않는다
        try:
            r = self._http.get(f"{BASE}/{API_ID[api]}/{self._key}", params=params)
        except httpx.HTTPError as e:
            raise LiveError("network", KEY_ENV, type(e).__name__) from None
        # shortcut: 허브의 인증 실패·한도 초과 응답 형식은 명세에 없어 HTTP 상태로만 구분한다. 실호출 후 확인 필요.
        if r.status_code in (401, 403):
            raise LiveError("bad_key", KEY_ENV, f"HTTP {r.status_code}")
        if r.status_code == 429:
            raise LiveError("quota", KEY_ENV, "HTTP 429")
        if r.status_code >= 400:
            raise LiveError("network", KEY_ENV, f"HTTP {r.status_code}")
        try:
            return r.json()
        except ValueError:
            raise LiveError("network", KEY_ENV, "JSON이 아닌 응답") from None
