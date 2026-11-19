"""농업기상 수집기: 지점 목록(제주 필터)·일자료 변환·365일 분할·오류 분류·이어받기. 가짜 서버만 쓴다."""
import json
from datetime import date

import httpx
import pytest

from jejuagent.data.live.agri_weather import AgriWeatherClient, collect_agri_weather, daily_rows, jeju_stations
from jejuagent.data.live.errors import LiveError

KEY = "test-key"


def xml(items, code="200", tag="Result_Code"):
    body = "".join("<item>" + "".join(f"<{k}>{v}</{k}>" for k, v in it.items()) + "</item>" for it in items)
    return (f'<?xml version="1.0" encoding="UTF-8"?><response><header><{tag}>{code}</{tag}></header><body>'
            f"<Total_Count>{len(items)}</Total_Count><items>{body}</items></body></response>")


STN = [{"Obsr_Spot_Code": "A1", "Obsr_Spot_Nm": "제주시 한림", "Instl_La": "33.4", "Instl_Lo": "126.3", "Instl_Al": "30"},
       {"Obsr_Spot_Code": "A2", "Obsr_Spot_Nm": "고도 없음", "Instl_La": "33.3", "Instl_Lo": "126.5", "Instl_Al": ""}]


def day(d, t=5.0):
    return {"obsr_Spot_Cd": "A1", "date_Time": d, "tmprt_150": t, "tmprt_150Top": t + 3, "tmprt_150Lwet": t - 3, "rn": "1.5"}


def server(calls=None, days=3):
    def h(req):
        q = dict(req.url.params)
        if calls is not None:
            calls.append(q)
        if req.url.path.endswith("getObsrSpotList"):
            return httpx.Response(200, text=xml(STN))
        return httpx.Response(200, text=xml([day(f"2024-01-0{i + 1}") for i in range(days)], tag="result_Code"))
    return httpx.MockTransport(h)


def test_jeju_stations_filter_and_drop_missing_elevation():
    calls = []
    st = jeju_stations(AgriWeatherClient(KEY, server(calls)))
    assert st == [{"code": "A1", "name": "제주시 한림", "lat": 33.4, "lon": 126.3, "elevation_m": 30.0}]
    assert calls[0]["Do_Se_Code"] == "8" and calls[0]["serviceKey"] == KEY


def test_daily_rows_convert_and_split_over_365_days():
    calls = []
    c = AgriWeatherClient(KEY, server(calls, days=2))
    rows = daily_rows(c, {"code": "A1", "name": "n", "lat": 1.0, "lon": 2.0, "elevation_m": 3.0}, date(2023, 1, 1), date(2024, 12, 31))
    assert len(calls) == 3                      # 2023 전체, 2024-01-01~12-30, 2024-12-31 (365일 분할)
    assert calls[0]["begin_Date"] == "2023-01-01" and calls[0]["end_Date"] == "2023-12-31"
    r = rows[0]
    assert (r["tmean"], r["tmax"], r["tmin"], r["precip"], r["station"], r["elevation_m"]) == (5.0, 8.0, 2.0, 1.5, "A1", 3.0)


@pytest.mark.parametrize("status,kind", [(401, "bad_key"), (403, "bad_key"), (429, "quota"), (500, "network")])
def test_http_errors(status, kind):
    with pytest.raises(LiveError) as e:
        AgriWeatherClient(KEY, httpx.MockTransport(lambda r: httpx.Response(status))).get("/x", {})
    assert e.value.kind == kind and KEY not in str(e.value)


def test_gateway_and_result_code_errors_and_no_key():
    gw = ("<OpenAPI_ServiceResponse><cmmMsgHeader><returnAuthMsg>SERVICE_KEY_IS_NOT_REGISTERED_ERROR</returnAuthMsg>"
          "</cmmMsgHeader></OpenAPI_ServiceResponse>")
    with pytest.raises(LiveError) as e:
        AgriWeatherClient(KEY, httpx.MockTransport(lambda r: httpx.Response(200, text=gw))).get("/x", {})
    assert e.value.kind == "bad_key"
    with pytest.raises(LiveError) as e2:
        AgriWeatherClient(KEY, httpx.MockTransport(lambda r: httpx.Response(200, text=xml([], code="101")))).get("/x", {})
    assert e2.value.kind == "bad_key"
    with pytest.raises(LiveError) as e3:
        AgriWeatherClient("", httpx.MockTransport(lambda r: httpx.Response(200))).get("/x", {})
    assert e3.value.kind == "no_key"


def test_network_error_does_not_leak_key_and_https_falls_back_to_http():
    seen = []

    def boom(req):
        seen.append(req.url.scheme)
        raise httpx.ConnectError(f"fail {req.url}")
    with pytest.raises(LiveError) as e:
        AgriWeatherClient(KEY, httpx.MockTransport(boom)).get("/x", {})
    assert e.value.kind == "network" and KEY not in str(e.value) and KEY not in e.value.detail and seen == ["https", "http"]


def test_collect_resumes_and_snapshots(tmp_path):
    first = collect_agri_weather(AgriWeatherClient(KEY, server(days=2), max_calls=1), date(2024, 1, 1), date(2024, 1, 2), "t", tmp_path)
    assert not first["done"] and first["error"]["kind"] == "quota"
    second = collect_agri_weather(AgriWeatherClient(KEY, server(days=2)), date(2024, 1, 1), date(2024, 1, 2), "t", tmp_path)
    assert second["done"] and second["stations"] == 1
    snap = json.loads((tmp_path / "t.json").read_text(encoding="utf-8"))
    assert len(snap["data"]) == 2 and snap["meta"]["synthetic"] is False and not (tmp_path / "_state_t.json").exists()


def test_implausible_temperature_day_is_dropped():
    bad = {**day("2024-01-02"), "tmprt_150Lwet": "-33.4"}
    handler = lambda r: httpx.Response(200, text=xml([day("2024-01-01"), bad, {**day("2024-01-03"), "tmprt_150": ""}], tag="result_Code"))
    c = AgriWeatherClient(KEY, httpx.MockTransport(handler))
    rows = daily_rows(c, {"code": "A1", "name": "n", "lat": 1.0, "lon": 2.0, "elevation_m": 3.0}, date(2024, 1, 1), date(2024, 1, 3))
    assert [r["date"] for r in rows] == ["2024-01-01"]       # 센서 오류(-33.4)와 평균기온 없는 날은 제외
