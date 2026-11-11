import numpy as np
import pytest

from jejuagent.catalog.profile import profile
from jejuagent.criteria.suitability import ITEM_INDICATOR, criteria_rows, evaluate
from jejuagent.geo import dem
from jejuagent.geo.climate import SEED_PATH, estimate_site, limitations, seed_module, site_inputs, synthetic_aws
from jejuagent.sandbox import run_generated_code

pytestmark = pytest.mark.skipif(not dem._files(), reason="DEM 도엽 없음")
COAST, HIGH = (33.5170, 126.5300), (33.38, 126.54)   # 제주시 해안, 한라산 고지대


@pytest.fixture(scope="module")
def aws():
    return synthetic_aws()


def _station(aws, i):
    r = aws[aws.station == f"SYN{i:02d}"].iloc[0]
    return r.lat, r.lon


def test_synthetic_is_marked_and_on_land(aws):
    assert aws.attrs["synthetic"] and aws.station.str.startswith("SYN").all()
    st = aws.groupby("station")[["lat", "lon"]].first()
    assert all(dem.is_land(a, b) for a, b in st.itertuples(index=False))
    assert aws.groupby("station").elevation_m.first().max() > 600     # 고지대 관측소가 있다


def test_highland_colder_than_coast(aws):
    hi, co = estimate_site(aws, *HIGH), estimate_site(aws, *COAST)
    hz, cz = hi["site_indicators"]["elevation_m"], co["site_indicators"]["elevation_m"]
    assert hz > cz + 500
    d = co["site_indicators"]["annual_mean_c"] - hi["site_indicators"]["annual_mean_c"]
    assert d > 0 and abs(d - 0.0065 * (hz - cz)) < 1.5               # 감률 6.5℃/km 근처
    assert hi["site_indicators"]["extreme_min_c"] < co["site_indicators"]["extreme_min_c"]


def test_estimate_close_to_observation_at_station(aws):
    lat, lon = _station(aws, 4)
    obs = aws[aws.station == "SYN04"].tmean.mean()
    est = estimate_site(aws, lat, lon)["site_indicators"]["annual_mean_c"]
    assert abs(est - obs) < 0.7


def test_cross_validation_beats_nearest(aws):
    cv = estimate_site(aws, *COAST)["cross_validation"]
    g = cv[cv.variable == "tmean"].set_index("method")
    assert g.loc["idw_lapse_fixed", "mae_daily_c"] < g.loc["nearest_station", "mae_daily_c"]
    assert g.loc["idw_lapse_fixed", "mae_daily_c"] < g.loc["idw_no_elevation", "mae_daily_c"]
    assert 5 < g.loc["idw_lapse_fitted", "lapse_c_per_km"] < 8        # 합성 진값 6.5 근처
    assert (cv.note.str.contains("합성")).all()


def test_derived_indicators_are_reference_only(aws):
    out = estimate_site(aws, *HIGH)
    ind = out["site_indicators"]
    for k in ("annual_mean_c", "extreme_min_c", "days_le_minus5_per_year", "days_le_0_per_year",
              "growing_mean_c", "precip_mm_per_year"):
        assert np.isfinite(ind[k])
    assert ind["days_le_0_per_year"] >= ind["days_le_minus5_per_year"] and ind["synthetic"]
    text = " ".join(map(str, out["limitations"].text)) + str(out["suitability"].to_dict())
    assert "한계 초과" not in text and "동해 위험" not in text


def test_suitability_reads_only_temperature_items_and_marks_missing():
    rows = criteria_rows()
    assert set(rows.item) <= set(ITEM_INDICATOR)
    assert not rows.item.str.contains("동해|한계|극최저|저온일수").any()
    s = evaluate({"annual_mean_c": 15.5, "growing_mean_c": 19.0})
    garlic = s[s.crop == "마늘"]
    assert (garlic.result == "근거 부족").all() and garlic.site_value.notna().all() and garlic.source_id.eq("").all()
    cit = s[(s.crop == "감귤") & (s.stage == "재배 가능 하한")]
    assert cit.result.iloc[0] == "충족" and cit.source_id.iloc[0] == "moon2015" and cit.confidence.iloc[0] == "높음"
    low = evaluate({"annual_mean_c": 13.0, "growing_mean_c": 19.0}, ["감귤"])
    assert low[low.stage == "재배 가능 하한"].result.iloc[0] == "미충족"
    carrot = s[(s.crop == "당근") & (s.item == "생육적온")]
    assert carrot.result.iloc[0] == "충족"                          # 18~21 안의 19.0
    assert (s[s.criterion == "기준표에 값 없음(미확보)"].result == "근거 부족").all()
    assert set(s.result) <= {"충족", "미충족", "근거 부족"}
    assert evaluate({"annual_mean_c": 15.5, "growing_mean_c": float("nan")}, ["무"]).result.eq("근거 부족").all()


def test_out_of_range_site_rejected(aws):
    with pytest.raises(ValueError, match="바다"):
        site_inputs(aws, 33.53, 126.53)


def test_limitations_present(aws):
    joined = "\n".join(estimate_site(aws, *COAST)["limitations"].text)
    for key in ("90m DEM", "경사", "일사", "관측소 수", "판정하지 않는다", "합성"):
        assert key in joined
    assert limitations(True)[-1] == seed_module().SYNTHETIC_NOTE and len(limitations()) == len(limitations(True)) - 1


ARTIFACTS = [
    {"id": "site_markers", "kind": "geo", "columns": [{"name": "lat", "dtype": "float"}, {"name": "lon", "dtype": "float"},
                                                       {"name": "annual_mean_c", "dtype": "float"}]},
    {"id": "site_indicators", "kind": "metrics"},
    {"id": "suitability", "kind": "table", "columns": [{"name": "result", "dtype": "str"}]},
    {"id": "cross_validation", "kind": "table", "columns": [{"name": "mae_daily_c", "dtype": "float"}]},
    {"id": "limitations", "kind": "table", "columns": [{"name": "text", "dtype": "str"}]},
]
PARAMS = {"lapse_c_per_km": 6.5, "idw_power": 2.0, "growing_months": "10,11,12,1,2,3", "synthetic": True}


def test_sandbox_run_real_inputs(aws):
    code = SEED_PATH.read_text(encoding="utf-8")
    r = run_generated_code(code, site_inputs(aws, *COAST), PARAMS, artifacts=ARTIFACTS, timeout_s=120)
    assert r.ok, (r.failure, r.message, r.problems)
    direct = estimate_site(aws, *COAST)
    assert abs(r.outputs["site_indicators"]["annual_mean_c"] - direct["site_indicators"]["annual_mean_c"]) < 1e-9


def test_sandbox_mock(aws):
    code = SEED_PATH.read_text(encoding="utf-8")
    profiles = {k: profile(v, k) for k, v in site_inputs(aws, *COAST).items()}
    r = run_generated_code(code, None, PARAMS, profiles=profiles, artifacts=ARTIFACTS, timeout_s=120)
    assert r.ok and r.details["mock"] is True, (r.failure, r.message, r.problems)
