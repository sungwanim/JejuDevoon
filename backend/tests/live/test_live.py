import json
import logging
import shutil

import httpx
import pytest

from jejuagent.catalog.catalog import ROOT
from synth_fixtures import write_test_snapshots
from jejuagent.data.live.errors import LiveError
from jejuagent.data.live.hub import HubClient
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
    assert "13t6aat1at6166111Dtt1taa1ta1661t/" + SECRET in str(calls[0].url)  # 앞의 긴 문자열은 공개 명세서의 API ID (비밀값 아님)


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
        write_test_snapshots(tmp_path / "snapshots")   # 실데이터 스냅샷(개발 PC에만 있음) 대신 테스트용 파일
    return LiveRegistry(snapshots_dir=tmp_path / "snapshots", catalog_dir=tmp_path / "catalog", live=live, hub=hub,
                        start="20240101", end="20240201")


def test_registry_live_then_snapshot_pinned(tmp_path):
    df = make_reg(tmp_path, HubClient(SECRET, hub_server(3))).load("jdh_agri_daily_trade")
    assert df.attrs["data_mode"] == "live" and len(df) == 3 * 18
    assert df["averagePrice"].dtype.kind == "f" and len(df.attrs["snapshot_version"]) == 16
    saved = json.loads((tmp_path / "snapshots/live/jdh_agri_daily_trade.json").read_text(encoding="utf-8"))
    assert saved["meta"]["version_hash"] == version_hash(saved["data"])
    # 라이브를 끄면 고정된 스냅샷을 쓴다
    d2 = make_reg(tmp_path, None, live=False).load("jdh_agri_daily_trade")
    assert d2.attrs["data_mode"] == "snapshot" and len(d2) == len(df)


@pytest.mark.parametrize("status,kind", [(401, "bad_key"), (429, "quota"), (500, "network")])
def test_registry_fallback(tmp_path, status, kind):
    reg = make_reg(tmp_path, HubClient(SECRET, httpx.MockTransport(lambda r: httpx.Response(status))))
    df = reg.load("jdh_agri_daily_trade")
    assert df.attrs["data_mode"] == "fallback" and len(df) > 0
    r = df.attrs["fallback_reason"]
    assert r["kind"] == kind and r["cause"] and r["fix"] and reg.notices[0]["dataset_id"] == "jdh_agri_daily_trade"


def test_registry_fallback_no_key(tmp_path, monkeypatch):
    monkeypatch.delenv("JEJU_HUB_PROJECT_KEY", raising=False)
    df = make_reg(tmp_path, HubClient(None, hub_server())).load("jdh_agri_daily_trade")
    assert df.attrs["data_mode"] == "fallback" and df.attrs["fallback_reason"]["kind"] == "no_key"


def test_csv_dataset_not_live():
    assert LiveRegistry(live=False).load("seogwipo_citrus_production").attrs["data_mode"] == "snapshot"
