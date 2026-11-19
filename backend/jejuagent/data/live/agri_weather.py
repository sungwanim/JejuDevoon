"""농촌진흥청 국립농업과학원 농업기상 API 수집기. 명세: data/docs/schemas/OPEN API기술명세서_농업기상 *.hwpx

지점: .../1390802/AgriWeather/getObsrSpotList  (Do_Se_Code=8 이 제주특별자치도) -> 코드, 이름, 설치 위도·경도·고도
일자료: .../1390802/AgriWeather/WeatherObsrInfo/V4/InsttWeather/getWeatherTermDayList4
        begin_Date/end_Date(YYYY-MM-DD, 최대 365일), obsr_Spot_Cd, Page_No, Page_Size(최대 100). 인증은 serviceKey(공공데이터포털 키).
응답은 XML. 태그 대소문자가 API마다 달라(Result_Code / result_Code) 소문자로 비교한다.
일자료 -> 표준 스키마: tmprt_150(평균)->tmean, tmprt_150Lwet(최저)->tmin, tmprt_150Top(최고)->tmax, rn->precip.
shortcut: 명세는 SSL 미지원이라고 적었으나 https를 먼저 시도하고 연결 오류면 http로 한 번 더 시도한다(https가 되면 http는 쓰지 않는다).
  오류 응답 형식은 명세의 코드표만 확인했고 실호출은 해 보지 못했다.
"""
from __future__ import annotations

import json
import logging
import os
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from pathlib import Path

import httpx

from .errors import LiveError
from .snapshot import LIVE_DIR, save_snapshot

log = logging.getLogger(__name__)
KEY_ENV = "DATA_GO_KR_SERVICE_KEY"
HOST = "apis.data.go.kr/1390802/AgriWeather"
STATION_PATH = "/getObsrSpotList"
DAILY_PATH = "/WeatherObsrInfo/V4/InsttWeather/getWeatherTermDayList4"
JEJU_DO = "8"           # 도구분코드: 제주특별자치도
PAGE = 100
MAX_SPAN = 365          # 한 번에 조회 가능한 최대 일수
_BAD_KEY = {"101"}
PLAUSIBLE_C = (-30.0, 45.0)   # 제주 기온으로 불가능한 값(센서 오류, 실제로 -33.4가 있었다)이 든 날은 버린다. shortcut: 범위 검사뿐, 급변 검사는 안 함
DAILY_FIELDS = {"tmean": "tmprt_150", "tmin": "tmprt_150lwet", "tmax": "tmprt_150top", "precip": "rn"}


def _items(xml_text: str) -> tuple[str, int, list[dict]]:
    """XML -> (결과코드, 전체 건수, 항목 목록[소문자 태그 -> 문자열]). 형식이 아니면 ParseError/ValueError."""
    root = ET.fromstring(xml_text)
    low = {e.tag.lower(): (e.text or "").strip() for e in root.iter() if len(e) == 0}
    code = low.get("result_code") or low.get("returnreasoncode") or ""
    items = [{c.tag.lower(): (c.text or "").strip() for c in it} for it in root.iter("item")]
    return code, int(low.get("total_count") or 0), items


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


class AgriWeatherClient:
    def __init__(self, service_key: str | None = None, transport: httpx.BaseTransport | None = None, max_calls: int = 900):
        self._key = service_key if service_key is not None else os.environ.get(KEY_ENV, "")
        self._http = httpx.Client(transport=transport, timeout=30)
        self.max_calls, self.calls, self._scheme = max_calls, 0, "https"

    def get(self, path: str, params: dict) -> tuple[int, list[dict]]:
        if not self._key:
            raise LiveError("no_key", KEY_ENV)
        if self.calls >= self.max_calls:
            raise LiveError("quota", KEY_ENV, f"자체 한도 {self.max_calls}건 (개발계정은 하루 1,000건)")
        self.calls += 1
        try:
            r = self._request(path, params)
        except httpx.HTTPError as e:
            raise LiveError("network", KEY_ENV, type(e).__name__) from None   # 예외 문자열엔 키가 든 URL이 있어 클래스명만
        if r.status_code in (401, 403):
            raise LiveError("bad_key", KEY_ENV, f"HTTP {r.status_code}")
        if r.status_code == 429:
            raise LiveError("quota", KEY_ENV, "HTTP 429")
        if r.status_code >= 400:
            raise LiveError("network", KEY_ENV, f"HTTP {r.status_code}")
        upper = r.text.upper().replace("_", " ")
        if "SERVICE KEY" in upper or "LIMITED NUMBER" in upper:   # 게이트웨이 오류(XML)
            raise LiveError("quota" if "LIMITED NUMBER" in upper else "bad_key", KEY_ENV, "게이트웨이 오류 응답")
        try:
            code, total, items = _items(r.text)
        except (ET.ParseError, ValueError):
            raise LiveError("network", KEY_ENV, "예상하지 못한 응답 형식") from None
        if code in _BAD_KEY:
            raise LiveError("bad_key", KEY_ENV, f"resultCode {code}")
        if code != "200":
            raise LiveError("network", KEY_ENV, f"resultCode {code}")
        return total, items

    def _request(self, path: str, params: dict) -> httpx.Response:
        q = {"serviceKey": self._key, **params}
        try:
            return self._http.get(f"{self._scheme}://{HOST}{path}", params=q)
        except httpx.ConnectError:
            if self._scheme == "http":
                raise
            self._scheme = "http"   # shortcut: 명세가 SSL 미지원이라고 적었다. https 연결 자체가 안 될 때만 한 번 내려간다
            return self._http.get(f"http://{HOST}{path}", params=q)

    def paged(self, path: str, params: dict) -> list[dict]:
        out, page = [], 1
        while True:
            total, items = self.get(path, {**params, "Page_No": page, "Page_Size": PAGE})
            out += items
            if not items or page * PAGE >= total:
                return out
            page += 1


def jeju_stations(client: AgriWeatherClient) -> list[dict]:
    """제주 관측지점: [{code, name, lat, lon, elevation_m}]. 좌표나 고도가 비어 있는 지점은 뺀다."""
    out = []
    for it in client.paged(STATION_PATH, {"Do_Se_Code": JEJU_DO}):
        lat, lon, alt = _num(it.get("instl_la")), _num(it.get("instl_lo")), _num(it.get("instl_al"))
        if lat is not None and lon is not None and alt is not None:
            out.append({"code": it["obsr_spot_code"], "name": it.get("obsr_spot_nm", ""), "lat": lat, "lon": lon, "elevation_m": alt})
    return out


def daily_rows(client: AgriWeatherClient, st: dict, start: date, end: date) -> list[dict]:
    """한 지점의 [start, end] 일자료를 365일 단위로 나눠 받아 표준 스키마 행으로. 평균기온이 없거나 기온이 상식 범위(PLAUSIBLE_C) 밖인 날은 뺀다."""
    rows, cur = [], start
    while cur <= end:
        stop = min(cur + timedelta(days=MAX_SPAN - 1), end)
        for it in client.paged(DAILY_PATH, {"begin_Date": cur.isoformat(), "end_Date": stop.isoformat(), "obsr_Spot_Cd": st["code"]}):
            vals = {k: _num(it.get(f)) for k, f in DAILY_FIELDS.items()}
            temps = [vals[k] for k in ("tmean", "tmin", "tmax")]
            if vals["tmean"] is None or any(t is not None and not PLAUSIBLE_C[0] <= t <= PLAUSIBLE_C[1] for t in temps):
                continue
            rows.append({"station": st["code"], "name": st["name"], "lat": st["lat"], "lon": st["lon"],
                         "elevation_m": st["elevation_m"], "date": it["date_time"], **vals})
        cur = stop + timedelta(days=1)
    return rows


def collect_agri_weather(client: AgriWeatherClient, start: date, end: date, name: str = "jeju_weather_daily",
                         directory: Path | None = None) -> dict:
    """제주 지점 전체를 지점 단위로 받아 진행 상태를 파일에 남긴다(한도·오류로 멈춰도 같은 명령으로 이어받기). 끝나면 스냅샷으로 고정.
    반환: {"done", "remaining", "stations", "calls", "error"}"""
    d = Path(directory) if directory else LIVE_DIR
    d.mkdir(parents=True, exist_ok=True)
    sp = d / f"_state_{name}.json"
    s = json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else {"stations": None, "done": [], "rows": []}
    err = None
    try:
        if s["stations"] is None:
            s["stations"] = jeju_stations(client)
        for st in s["stations"]:
            if st["code"] in s["done"]:
                continue
            s["rows"] += daily_rows(client, st, start, end)
            s["done"].append(st["code"])
            sp.write_text(json.dumps(s, ensure_ascii=False), encoding="utf-8")
    except LiveError as e:
        err = e.as_dict()
    sp.write_text(json.dumps(s, ensure_ascii=False), encoding="utf-8")
    n = len(s["stations"] or [])
    remaining = (n - len(s["done"])) if s["stations"] is not None else -1
    if remaining == 0 and s["rows"]:
        save_snapshot(name, s["rows"], {"source": "농촌진흥청 국립농업과학원 농업기상 관측데이터(일자료)",
                                        "source_url": "https://" + HOST + DAILY_PATH,
                                        "stations": [x["code"] for x in s["stations"]], "range": [start.isoformat(), end.isoformat()]}, d)
        sp.unlink(missing_ok=True)
    return {"done": remaining == 0 and bool(s["rows"]), "remaining": remaining, "stations": n, "calls": client.calls, "error": err}
