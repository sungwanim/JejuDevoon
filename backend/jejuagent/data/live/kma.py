"""공공데이터포털(data.go.kr) 기상청 수집기: 지점정보 + AWS 일자료. 키는 DATA_GO_KR_SERVICE_KEY (환경변수).

확인된 것 (공식 문서로 읽음):
- 지점정보 AWS 지점: https://apis.data.go.kr/1360000/WethrBasicInfoService/getAwsKORNAData
  요청 ServiceKey, pageNo, numOfRows(필수), dataType(XML|JSON). 출처: https://www.data.go.kr/data/15058846/openapi.do
미확인 (이 폴더의 명세와 사이트에서 읽지 못함 -> 추측하지 않고 사용자 명세 파일로 받는다):
- AWS 일자료의 URL·요청 파라미터·응답 필드명, 지점정보 응답의 JSON 필드명(문서엔 한글 설명뿐), 일일 한도 수치(10,000건은 티켓 기준).
- 오류 코드 30/31/22 등은 공공데이터포털 공통 코드로 알려진 값이며 이 서비스 문서로는 확인하지 못했다.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import httpx

from .errors import LiveError
from .snapshot import LIVE_DIR, save_snapshot

log = logging.getLogger(__name__)
KEY_ENV = "DATA_GO_KR_SERVICE_KEY"
STATION_URL = "https://apis.data.go.kr/1360000/WethrBasicInfoService/getAwsKORNAData"
DAILY_LIMIT = 10_000  # 개발계정 일일 한도 (티켓 기준)
_BAD_KEY = {"20", "30", "31", "32", "33"}   # 접근거부/미등록/기간만료/IP/서명 계열
_QUOTA = {"22"}


class DataGoClient:
    """호출 횟수를 세어 max_calls에 닿으면 quota 오류를 낸다 (서버가 거절하기 전에 스스로 멈춤)."""

    def __init__(self, service_key: str | None = None, transport: httpx.BaseTransport | None = None, max_calls: int = DAILY_LIMIT):
        self._key = service_key if service_key is not None else os.environ.get(KEY_ENV, "")
        self._http = httpx.Client(transport=transport, timeout=30)
        self.max_calls, self.calls = max_calls, 0

    def get_items(self, url: str, params: dict, rows_per_page: int = 1000) -> list[dict]:
        if not self._key:
            raise LiveError("no_key", KEY_ENV)
        out: list[dict] = []
        page = 1
        while True:
            body = self._get(url, {**params, "pageNo": page, "numOfRows": rows_per_page})
            raw = body.get("items")
            items = raw.get("item", []) if isinstance(raw, dict) else (raw or [])
            items = [items] if isinstance(items, dict) else items
            out += items
            if not items or page * rows_per_page >= int(body.get("totalCount") or 0):
                return out
            page += 1

    def _get(self, url: str, params: dict) -> dict:
        if self.calls >= self.max_calls:
            raise LiveError("quota", KEY_ENV, f"자체 한도 {self.max_calls}건")
        self.calls += 1
        try:
            r = self._http.get(url, params={"ServiceKey": self._key, "dataType": "JSON", **params})
        except httpx.HTTPError as e:
            raise LiveError("network", KEY_ENV, type(e).__name__) from None  # 예외 문자열엔 키가 든 URL이 있어 클래스명만
        if r.status_code in (401, 403):
            raise LiveError("bad_key", KEY_ENV, f"HTTP {r.status_code}")
        if r.status_code == 429:
            raise LiveError("quota", KEY_ENV, "HTTP 429")
        if r.status_code >= 400:
            raise LiveError("network", KEY_ENV, f"HTTP {r.status_code}")
        try:
            resp = r.json()["response"]
            code, msg = str(resp["header"]["resultCode"]), resp["header"].get("resultMsg", "")
        except (ValueError, KeyError, TypeError):
            # 포털은 인증 오류를 XML로 돌려주기도 한다 -> 본문에서 키 오류 문구를 찾는다
            if "SERVICE KEY" in r.text.upper().replace("_", " "):
                raise LiveError("bad_key", KEY_ENV, "인증 오류 응답") from None
            raise LiveError("network", KEY_ENV, "예상하지 못한 응답 형식") from None
        if code in _BAD_KEY:
            raise LiveError("bad_key", KEY_ENV, f"resultCode {code}")
        if code in _QUOTA:
            raise LiveError("quota", KEY_ENV, f"resultCode {code}")
        if code != "00":
            raise LiveError("network", KEY_ENV, f"resultCode {code} {msg}")
        return resp["body"]


def collect_stations(client: DataGoClient, directory: Path | None = None) -> Path:
    """AWS 지점 전체를 원본 필드 그대로 snapshots/live/kma_aws_stations_raw.json 에 저장한다.
    응답 필드명이 문서에 한글 설명뿐이라 제주 필터링은 필드명을 확인한 뒤 jeju_stations()로 한다."""
    return save_snapshot("kma_aws_stations_raw", client.get_items(STATION_URL, {}),
                         {"source": "기상청 지점정보 getAwsKORNAData", "source_url": STATION_URL}, directory)


def jeju_stations(items: list[dict], id_field: str, filter_field: str, pattern: str = "제주") -> list[str]:
    """filter_field 값에 pattern이 들어있는 지점의 id_field 목록. 필드명이 없으면 실제 필드명을 알려주며 실패한다."""
    if items and (id_field not in items[0] or filter_field not in items[0]):
        raise KeyError(f"지점정보에 {id_field!r}/{filter_field!r} 필드가 없습니다. 실제 필드: {sorted(items[0])}")
    return [str(i[id_field]) for i in items if pattern in str(i[filter_field])]


@dataclass
class DailySpec:
    """AWS 일자료 API 명세. 문서로 확인하지 못해 기본값이 없다 -> 사용자가 활용가이드를 보고 채운다."""
    url: str
    station_param: str
    start_param: str
    end_param: str
    date_fmt: str                     # strftime 형식 (명세로 확인한 값을 넣을 것)
    extra_params: dict = field(default_factory=dict)

    @classmethod
    def from_file(cls, path: str | Path) -> "DailySpec":
        return cls(**json.loads(Path(path).read_text(encoding="utf-8")))


def collect_daily(client: DataGoClient, spec: DailySpec, stations: list[str], start_year: int, end_year: int,
                  name: str = "kma_aws_daily_jeju", directory: Path | None = None) -> dict:
    """(지점, 연도) 단위로 받아 진행 상태를 파일에 남긴다. 한도·오류로 멈추면 저장하고, 같은 명령을 다시 실행하면 이어받는다.
    모두 끝나면 스냅샷으로 고정하고 상태 파일을 지운다. 반환: {"done", "remaining", "calls", "error"}"""
    d = Path(directory) if directory else LIVE_DIR
    d.mkdir(parents=True, exist_ok=True)
    sp = d / f"_state_{name}.json"
    st = json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else {"done": [], "rows": []}
    err = None
    for s in stations:
        for y in range(start_year, end_year + 1):
            if f"{s}:{y}" in st["done"]:
                continue
            params = {**spec.extra_params, spec.station_param: s, spec.start_param: date(y, 1, 1).strftime(spec.date_fmt),
                      spec.end_param: date(y, 12, 31).strftime(spec.date_fmt)}
            try:
                st["rows"] += client.get_items(spec.url, params)
            except LiveError as e:
                err = e.as_dict()
                break
            st["done"].append(f"{s}:{y}")
            sp.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
        if err:
            break
    remaining = len(stations) * (end_year - start_year + 1) - len(st["done"])
    if remaining == 0:
        save_snapshot(name, st["rows"], {"source": "기상청 AWS 일자료", "source_url": spec.url, "stations": stations,
                                         "years": [start_year, end_year]}, d)
        sp.unlink(missing_ok=True)
    return {"done": remaining == 0, "remaining": remaining, "calls": client.calls, "error": err}
