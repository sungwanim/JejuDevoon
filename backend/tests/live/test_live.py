import json
import logging
import shutil

import httpx
import pytest

from jejuagent.catalog.catalog import ROOT
from jejuagent.data.live.errors import LiveError
from jejuagent.data.live.hub import HubClient
from jejuagent.data.live.kma import DailySpec, DataGoClient, collect_daily, jeju_stations
from jejuagent.data.live.registry import LiveRegistry
from jejuagent.data.live.snapshot import version_hash

SECRET = "test-key"


def hub_server(total=250, calls=None):
    def h(req: httpx.Request):
        if calls is not None:
            calls.append(req)
        q = req.url.params
        n, lim = int(q["number"]), int(q["limit"])
        rows = [{"baseDate": "20240101", "cultivar": q["cultivar"], "averagePrice": str(i), "transactionVolume": "1",
                 "transactionAmount": "1"} for i in range(total)][(n - 1) * lim: n * lim]
        return httpx.Response(200, json={"totCnt": total, "hasMore": n * lim < total, "data": rows})
    return httpx.MockTransport(h)


def test_hub_pages_and_params():
    calls = []
    rows = HubClient(SECRET, hub_server(250, calls)).fetch("daily", "20240101", "20240201", "깐마늘", limit=500)
    assert len(rows) == 250 and len(calls) == 3                      # limit은 100으로 제한 -> 3페이지
    assert calls[0].url.params["limit"] == "100" and calls[0].url.params["cultivar"] == "깐마늘"
    assert "b1t41a11tD124baa4D42b7Dtt44b74tt/" + SECRET in str(calls[0].url)  # 앞의 긴 문자열은 공개 명세서의 API ID (비밀값 아님)


def test_hub_validation():
    c = HubClient(SECRET, hub_server())
    with pytest.raises(ValueError):
        c.fetch("daily", "20240101", "20240201", "")
    with pytest.raises(ValueError):
        c.fetch("moving_avg", "20240101", "20240201", "깐마늘", period=5)
    assert c.fetch("moving_avg", "20240101", "20240201", "깐마늘", period=30)


def test_no_key_message(monkeypatch):
    monkeypatch.delenv("JEJU_HUB_PROJECT_KEY", raising=False)
    with pytest.raises(LiveError) as e:
        HubClient(None, hub_server()).fetch("daily", "20240101", "20240201", "깐마늘")
    assert e.value.kind == "no_key" and "JEJU_HUB_PROJECT_KEY" in str(e.value) and ".env" in str(e.value)


@pytest.mark.parametrize("status,kind", [(401, "bad_key"), (403, "bad_key"), (429, "quota"), (503, "network")])
def test_hub_error_kinds(status, kind):
    c = HubClient(SECRET, httpx.MockTransport(lambda r: httpx.Response(status)))
    with pytest.raises(LiveError) as e:
        c.fetch("daily", "20240101", "20240201", "깐마늘")
    assert e.value.kind == kind and SECRET not in str(e.value) and SECRET not in repr(e.value.as_dict())


def test_network_error_hides_key(caplog):
    def boom(r):
        raise httpx.ConnectError("fail " + str(r.url))
    caplog.set_level(logging.DEBUG)
    with pytest.raises(LiveError) as e:
        HubClient(SECRET, httpx.MockTransport(boom)).fetch("daily", "20240101", "20240201", "깐마늘")
    assert e.value.kind == "network" and SECRET not in str(e.value) and e.value.__cause__ is None
    assert SECRET not in caplog.text and "hub GET" in caplog.text


def make_reg(tmp_path, hub, live=True):
    if not (tmp_path / "catalog").exists():
        shutil.copytree(ROOT / "catalog", tmp_path / "catalog")
        shutil.copytree(ROOT / "snapshots", tmp_path / "snapshots")
    return LiveRegistry(snapshots_dir=tmp_path / "snapshots", catalog_dir=tmp_path / "catalog", live=live, hub=hub,
                        start="20240101", end="20240201")


def test_registry_live_then_snapshot_pinned(tmp_path):
    df = make_reg(tmp_path, HubClient(SECRET, hub_server(3))).load("jdh_agri_daily_trade")
    assert df.attrs["data_mode"] == "live" and len(df) == 3 * 18 and not df.attrs["synthetic"]
    assert df["averagePrice"].dtype.kind == "f" and len(df.attrs["snapshot_version"]) == 16
    saved = json.loads((tmp_path / "snapshots/live/jdh_agri_daily_trade.json").read_text(encoding="utf-8"))
    assert saved["meta"]["version_hash"] == version_hash(saved["data"])
    # 라이브를 끄면 고정된 실데이터 스냅샷을 쓴다 (합성 샘플이 아님)
    d2 = make_reg(tmp_path, None, live=False).load("jdh_agri_daily_trade")
    assert d2.attrs["data_mode"] == "snapshot" and len(d2) == len(df) and not d2.attrs["synthetic"]


@pytest.mark.parametrize("status,kind", [(401, "bad_key"), (429, "quota"), (500, "network")])
def test_registry_fallback(tmp_path, status, kind):
    reg = make_reg(tmp_path, HubClient(SECRET, httpx.MockTransport(lambda r: httpx.Response(status))))
    df = reg.load("jdh_agri_daily_trade")
    assert df.attrs["data_mode"] == "fallback" and len(df) > 0 and df.attrs["synthetic"]
    r = df.attrs["fallback_reason"]
    assert r["kind"] == kind and r["cause"] and r["fix"] and reg.notices[0]["dataset_id"] == "jdh_agri_daily_trade"


def test_registry_fallback_no_key(tmp_path, monkeypatch):
    monkeypatch.delenv("JEJU_HUB_PROJECT_KEY", raising=False)
    df = make_reg(tmp_path, HubClient(None, hub_server())).load("jdh_agri_daily_trade")
    assert df.attrs["data_mode"] == "fallback" and df.attrs["fallback_reason"]["kind"] == "no_key"


def test_csv_dataset_not_live():
    assert LiveRegistry(live=False).load("seogwipo_citrus_production").attrs["data_mode"] == "snapshot"


# ---- 기상청 수집기 (가짜 서버, 응답 구조는 data.go.kr 공통 header/body/items/item 가정) ----

def kma_body(items, total, code="00"):
    return {"response": {"header": {"resultCode": code, "resultMsg": "x"}, "body": {"items": {"item": items}, "totalCount": total}}}


SPEC = DailySpec(url="https://fake/daily", station_param="stn", start_param="s", end_param="e", date_fmt="%Y%m%d")


def kma_server(calls):
    def h(req):
        calls.append(req)
        q = req.url.params
        return httpx.Response(200, json=kma_body([{"stn": q["stn"], "s": q["s"]}], 1))
    return httpx.MockTransport(h)


def test_kma_paging():
    def h(req):
        p = int(req.url.params["pageNo"])
        return httpx.Response(200, json=kma_body([{"i": p * 10 + k} for k in range(2)], 4))
    assert len(DataGoClient(SECRET, httpx.MockTransport(h)).get_items("https://fake", {}, rows_per_page=2)) == 4


def test_kma_error_codes():
    for code, kind in [("30", "bad_key"), ("22", "quota")]:
        c = DataGoClient(SECRET, httpx.MockTransport(lambda r, code=code: httpx.Response(200, json=kma_body([], 0, code))))
        with pytest.raises(LiveError) as e:
            c.get_items("https://fake", {})
        assert e.value.kind == kind
    xml = httpx.MockTransport(lambda r: httpx.Response(200, text="<OpenAPI_ServiceResponse>SERVICE_KEY_IS_NOT_REGISTERED_ERROR"))
    with pytest.raises(LiveError) as e:
        DataGoClient(SECRET, xml).get_items("https://fake", {})
    assert e.value.kind == "bad_key"
    with pytest.raises(LiveError) as e:
        DataGoClient("", xml).get_items("https://fake", {})
    assert e.value.kind == "no_key" and "DATA_GO_KR_SERVICE_KEY" in str(e.value)


def test_daily_resume_after_quota(tmp_path):
    calls = []
    stations, years = ["10", "20"], (2020, 2022)          # 6개 작업
    r1 = collect_daily(DataGoClient(SECRET, kma_server(calls), max_calls=4), SPEC, stations, *years, directory=tmp_path)
    assert not r1["done"] and r1["remaining"] == 2 and r1["error"]["kind"] == "quota"
    assert (tmp_path / "_state_kma_aws_daily_jeju.json").exists() and len(calls) == 4
    r2 = collect_daily(DataGoClient(SECRET, kma_server(calls), max_calls=4), SPEC, stations, *years, directory=tmp_path)
    assert r2["done"] and len(calls) == 6                  # 이미 받은 4건은 다시 호출하지 않음
    snap = json.loads((tmp_path / "kma_aws_daily_jeju.json").read_text(encoding="utf-8"))
    assert len(snap["data"]) == 6 and snap["meta"]["version_hash"] == version_hash(snap["data"])
    assert not (tmp_path / "_state_kma_aws_daily_jeju.json").exists()


def test_jeju_stations_field_check():
    items = [{"id": "1", "nm": "제주"}, {"id": "2", "nm": "서울"}]
    assert jeju_stations(items, "id", "nm") == ["1"]
    with pytest.raises(KeyError, match="실제 필드"):
        jeju_stations(items, "stnId", "nm")
