"""기상청 API허브 AWS 매분자료 수집기. 명세: data/docs/schemas/AWS매분자료조회_API명세서.pdf

요청: GET https://apihub.kma.go.kr/api/typ01/cgi-bin/url/nph-aws2_min?tm1&tm2&stn&disp&help&authKey  (인증키는 authKey 쿼리 인자)
조회 구간: 1개 지점이면 하루 이내, 전체 지점이면 10분 이내. 그래서 (지점, 날짜) 한 건씩 받아 일자료로 집계해 저장한다(1분 자료 원본은 저장하지 않는다).
응답: 텍스트. '#'로 시작하는 줄은 머리글, 데이터 줄은 12자리 시각으로 시작한다. 열 순서(명세 18종):
  TM STN WD1 WS1 WDS WSS WD10 WS10 TA RE RN-15m RN-60m RN-12H RN-DAY HM PA PS TD.  -50 이하는 결측·오류 표시.
키는 URL에 들어가므로 예외·로그에 URL을 쓰지 않는다.
shortcut: 일 강수량은 RN-DAY(일 누적)의 하루 최댓값으로 보았다(0시 초기화 가정, 명세에 초기화 시각 없음). 에러 응답 형식은
  명세의 표(401·403)만 확인했고 실호출은 해 보지 못했다.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import date, timedelta
from pathlib import Path

import httpx
import pandas as pd

from .errors import LiveError
from .snapshot import LIVE_DIR, save_snapshot

log = logging.getLogger(__name__)
KEY_ENV = "KMA_API_HUB_KEY"
URL = "https://apihub.kma.go.kr/api/typ01/cgi-bin/url/nph-aws2_min"
COLS = ["TM", "STN", "WD1", "WS1", "WDS", "WSS", "WD10", "WS10", "TA", "RE", "RN-15m", "RN-60m", "RN-12H", "RN-DAY", "HM", "PA", "PS", "TD"]
MIN_VALID = 1008        # 하루 1440분 중 기온이 유효한 분이 70% 미만이면 그 날은 버린다
_ROW = re.compile(r"^\s*\d{12}[\s,]")


def parse_minutes(text: str) -> pd.DataFrame:
    """응답 텍스트 -> 분 단위 표(COLS 열, 결측은 NaN). 구분자는 공백·쉼표 모두 받는다. 데이터 줄이 하나도 없으면 빈 표."""
    rows = []
    for line in text.splitlines():
        if _ROW.match(line):
            v = line.replace(",", " ").split()
            if len(v) >= len(COLS):
                rows.append(v[:len(COLS)])
    df = pd.DataFrame(rows, columns=COLS)
    for c in COLS[1:]:
        df[c] = pd.to_numeric(df[c], errors="coerce").where(lambda s: s > -50)
    return df


def daily_row(df: pd.DataFrame, day: date, stn: str) -> dict | None:
    """분 자료 하루치 -> 일자료 한 행 {station, date, tmean, tmin, tmax, precip}. 유효 분이 적으면 None."""
    ta = df["TA"].dropna()
    if len(ta) < MIN_VALID:
        return None
    rain = df["RN-DAY"].dropna()
    return {"station": str(stn), "date": day.isoformat(), "tmean": round(float(ta.mean()), 2), "tmin": float(ta.min()),
            "tmax": float(ta.max()), "precip": float(rain.max()) if len(rain) else None}


class KmaHubClient:
    def __init__(self, auth_key: str | None = None, transport: httpx.BaseTransport | None = None, max_calls: int = 5000):
        self._key = auth_key if auth_key is not None else os.environ.get(KEY_ENV, "")
        self._http = httpx.Client(transport=transport, timeout=60)
        self.max_calls, self.calls = max_calls, 0

    def minutes(self, stn: str, day: date) -> pd.DataFrame:
        if not self._key:
            raise LiveError("no_key", KEY_ENV)
        if self.calls >= self.max_calls:
            raise LiveError("quota", KEY_ENV, f"자체 한도 {self.max_calls}건")
        self.calls += 1
        d = day.strftime("%Y%m%d")
        params = {"tm1": d + "0000", "tm2": d + "2359", "stn": stn, "disp": 1, "help": 2, "authKey": self._key}
        try:
            r = self._http.get(URL, params=params)
        except httpx.HTTPError as e:
            raise LiveError("network", KEY_ENV, type(e).__name__) from None   # 예외 문자열엔 키가 든 URL이 있어 클래스명만
        if r.status_code in (401, 403):
            raise LiveError("bad_key", KEY_ENV, f"HTTP {r.status_code} (인증키 확인 또는 활용신청 필요)")
        if r.status_code == 429:
            raise LiveError("quota", KEY_ENV, "HTTP 429")
        if r.status_code >= 400:
            raise LiveError("network", KEY_ENV, f"HTTP {r.status_code}")
        return parse_minutes(r.text)


def load_stations(path: str | Path) -> list[dict]:
    """지점 CSV(code,name,lat,lon[,elevation_m]) -> [{code,name,lat,lon,elevation_m}]. 고도가 비면 DEM(90m)에서 구한다. 바다·격자 밖은 건너뛴다."""
    from ...catalog.loader import read_csv_auto
    from ...geo import get_elevation
    out = []
    for r in read_csv_auto(path).to_dict("records"):
        z = r.get("elevation_m")
        z = float(z) if z == z and z not in (None, "") else get_elevation(float(r["lat"]), float(r["lon"]))
        if z is not None:
            out.append({"code": str(r["code"]), "name": str(r.get("name", "")), "lat": float(r["lat"]), "lon": float(r["lon"]), "elevation_m": float(z)})
    return out


def collect_daily_hub(client: KmaHubClient, stations: list[dict], start: date, end: date,
                      name: str = "jeju_weather_daily", directory: Path | None = None) -> dict:
    """(지점, 날짜)마다 받아 일자료로 집계. 진행 상태를 파일에 남기므로 한도·오류로 멈춰도 같은 명령을 다시 실행하면 이어받는다.
    모두 끝나면 스냅샷으로 고정하고 상태 파일을 지운다. 반환: {"done", "remaining", "calls", "error", "skipped"}"""
    d = Path(directory) if directory else LIVE_DIR
    d.mkdir(parents=True, exist_ok=True)
    sp = d / f"_state_{name}.json"
    st = json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else {"done": [], "rows": [], "skipped": []}
    days = [start + timedelta(n) for n in range((end - start).days + 1)]
    err, since_save = None, 0
    for stn in stations:
        s = stn["code"]
        for day in days:
            key = f"{s}:{day.isoformat()}"
            if key in st["done"]:
                continue
            try:
                row = daily_row(client.minutes(s, day), day, s)
                if row:
                    row.update(name=stn["name"], lat=stn["lat"], lon=stn["lon"], elevation_m=stn["elevation_m"])
            except LiveError as e:
                err = e.as_dict()
                break
            st["done"].append(key)
            if row:
                st["rows"].append(row)
            else:
                st["skipped"].append(key)
            since_save += 1
            if since_save >= 20:
                sp.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8"); since_save = 0
        if err:
            break
    sp.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
    remaining = len(stations) * len(days) - len(st["done"])
    if remaining == 0:
        save_snapshot(name, st["rows"], {"source": "기상청 API허브 AWS 매분자료 -> 일자료 집계", "source_url": URL, "stations": [x["code"] for x in stations],
                                         "range": [start.isoformat(), end.isoformat()], "skipped_days": len(st["skipped"])}, d)
        sp.unlink(missing_ok=True)
    return {"done": remaining == 0, "remaining": remaining, "calls": client.calls, "error": err, "skipped": len(st["skipped"])}
