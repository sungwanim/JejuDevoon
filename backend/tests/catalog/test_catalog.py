import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
from fastapi.testclient import TestClient

from jejuagent.api.app import create_app
from jejuagent.llm import FakeLLM
from jejuagent.runner import SnapshotRegistry
from jejuagent.runner.stages import s3_load

reg = SnapshotRegistry()


def test_catalog_has_entries_with_required_fields():
    cat = reg.catalog()
    assert {e["id"] for e in cat} == {"seogwipo_citrus_production", "jdh_agri_daily_trade", "jdh_agri_trade_moving_avg",
                                         "synthetic_aws_daily", "jeju_vegetable_cultivation", "jeju_airport_noise",
                                         "jeju_urban_forest", "jeju_environmental_noise"}
    for e in cat:
        assert all(k in e for k in ("title", "source", "access", "license", "spatial_unit", "temporal_unit", "coverage", "columns", "notes"))
    assert "제주시" in next(e for e in cat if e["id"].startswith("seogwipo"))["notes"]
    assert all(e["synthetic"] and "합성" in e["notes"] for e in cat if e["id"].startswith("jdh_"))
    aws = next(e for e in cat if e["id"] == "synthetic_aws_daily")   # 티켓 16: 지점 기후용 합성 관측소 (실데이터 아님)
    assert aws["synthetic"] and aws["spatial_unit"] == "관측소" and "합성" in aws["title"] + aws["source"] + aws["notes"]
    assert reg.load("synthetic_aws_daily").attrs["synthetic"] is True
    assert json.load(open(reg.snapshots_dir / "jdh_agri_daily_trade.json", encoding="utf-8"))["meta"]["synthetic"] is True


def test_citrus_cp949_wide_and_profile():
    df = reg.load("seogwipo_citrus_production")
    assert df.attrs["encoding"] == "cp949" and len(df) == 495
    assert df["읍면동"].nunique() == 15 and set(df["구분"]) == {"농가수", "면적", "생산량"}
    from jejuagent.catalog import profile
    p = profile(df, "seogwipo_citrus_production", next(e for e in reg.catalog() if e["id"].startswith("seogwipo")))
    assert p["n_rows"] == 495 and p["encoding"] == "cp949" and len(p["version_hash"]) == 16
    c = {x["name"]: x for x in p["columns"]}["노지온주(조생)"]
    assert c["dtype"] == "float" and "ha" in c["unit"] and 3 <= len(c["samples"]) <= 5
    assert c["n_unique"] > 3 and c["min"] <= c["max"]
    assert p == profile(df, "seogwipo_citrus_production", next(e for e in reg.catalog() if e["id"].startswith("seogwipo")))
    json.dumps(p)


def test_trade_snapshot_string_numbers_and_zero_missing():
    d = reg.load("jdh_agri_daily_trade")
    assert d["averagePrice"].dtype == float and pd.api.types.is_datetime64_any_dtype(d["baseDate"])
    m = reg.load("jdh_agri_trade_moving_avg")
    assert m["priceMovingAverage"].isna().sum() >= 6 and (m["priceMovingAverage"].dropna() > 0).all()
    from jejuagent.catalog import profile
    pm = {x["name"]: x for x in profile(m, "x", next(e for e in reg.catalog() if e["id"].endswith("moving_avg")))["columns"]}
    assert pm["priceMovingAverage"]["null_pct"] > 0 and pm["priceMovingAverage"]["unit"] == "원/kg"
    assert pm["baseDate"]["dtype"] == "date"


def test_s3_skips_failed_and_records():
    class Tr:
        def add(self, *a, **k): pass
    ctx = SimpleNamespace(data=reg, trace=Tr())
    st = SimpleNamespace(selection={"selected": [{"dataset_id": "jdh_agri_daily_trade"}, {"dataset_id": "nope"}]},
                         data={}, profiles={}, load_failures=[])
    st = s3_load.run(st, ctx)
    assert list(st.data) == ["jdh_agri_daily_trade"] and list(st.profiles) == ["jdh_agri_daily_trade"]
    assert st.load_failures[0]["dataset_id"] == "nope"


def test_catalog_api_lists_entries():
    r = TestClient(create_app(lambda: FakeLLM([]), data=reg)).get("/api/catalog").json()
    assert len(r) == 8 and r[0]["title"]


def test_new_domain_datasets_load():
    reg = SnapshotRegistry()
    air = reg.load("jeju_airport_noise")
    assert air["공항"].eq("제주공항").all() and len(air) == 849 and air["소음도(단위:WECPNL)"].isna().sum() == 275
    forest = reg.load("jeju_urban_forest")
    assert len(forest) == 28 and forest["사업량(ha)"].dtype.kind == "f"
    noise = reg.load("jeju_environmental_noise")
    assert len(noise) == 140 and noise["위도"].between(33.2, 33.6).all() and noise["경도"].between(126.4, 126.7).all()


def test_real_weather_hidden_until_collected_then_replaces_synthetic(tmp_path):
    from jejuagent.runner.datasource import SnapshotRegistry as R
    ids = lambda r: {e["id"] for e in r.catalog()}
    r = R(snapshots_dir=tmp_path)
    assert "synthetic_aws_daily" in ids(r) and "jeju_weather_daily" not in ids(r)      # 수집 전
    (tmp_path / "live").mkdir()
    rows = [{"station": "A1", "name": "n", "lat": 33.4, "lon": 126.5, "elevation_m": 20.0, "date": "2024-01-01", "tmean": 5.0,
             "tmin": 2.0, "tmax": 8.0, "precip": 0.0}]
    (tmp_path / "live" / "jeju_weather_daily.json").write_text(json.dumps({"meta": {"synthetic": False}, "data": rows}), encoding="utf-8")
    assert "jeju_weather_daily" in ids(r) and "synthetic_aws_daily" not in ids(r)       # 수집 후
    df = r.load("jeju_weather_daily")
    assert len(df) == 1 and df["tmean"].iloc[0] == 5.0 and not df.attrs.get("synthetic")
