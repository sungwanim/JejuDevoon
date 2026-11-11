import json

import pytest

from jejuagent.criteria import CriteriaError, load_criteria
from jejuagent.criteria.loader import CROPS, DATA_PATH


@pytest.fixture(scope="module")
def t():
    return load_criteria()


def test_all_crops_present(t):
    assert set(t.crops()) == set(CROPS)


def test_every_found_value_has_source_location_url(t):
    for r in t.records:
        if not r.is_missing:
            s = t.source_of(r)
            assert s and s.url.startswith("http") and r.location, (r.crop, r.item)


def test_citrus_low_temp_days_is_at_most_5_and_checked(t):
    (r,) = t.get("감귤", "-5℃ 이하 저온일수(연중)")
    assert (r.value_type, r.max, r.min, r.unit) == ("threshold_max", 5, None, "일")
    assert r.original_checked is True
    assert "5일 이하" in r.location


def test_citrus_annual_mean_and_extreme_min(t):
    assert t.get("감귤", "연평균기온", grade=None)[0].min == 14.5
    assert t.get("감귤", "극최저기온(일최저기온 극값)")[0].min == -10.0
    assert [r.min for r in t.get("감귤", "극최저기온", grade="적지")] == [-7.0]


def test_radish_optimum_17_23_and_frost_0(t):
    assert any(r.min == 17 and r.max == 23 for r in t.get("무", "생육적온(낮)"))
    assert t.get("무", "동해(다 자란 무)")[0].min == 0


def test_carrot_and_cabbage_values_not_borrowed(t):
    assert t.get("당근", "생육적온")[0].min == 18 and t.get("당근", "생육적온")[0].max == 21
    assert t.get("양배추", "생육적온")[0].max == 20
    # 동해 한계는 당근에서 미확보로 남아 있어야 하고 값이 없어야 한다
    (m,) = t.missing("당근")
    assert m.min is None and m.max is None and m.source_id is None


def test_get_unknown_crop_raises(t):
    with pytest.raises(KeyError):
        t.get("배추")


def test_include_missing_flag(t):
    assert all(not r.is_missing for r in t.get("당근", include_missing=False))


def _write(tmp_path, mutate):
    doc = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    mutate(doc)
    p = tmp_path / "c.json"
    p.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return p


def test_loader_rejects_value_without_source(tmp_path):
    p = _write(tmp_path, lambda d: d["records"][0].update(source_id=None))
    with pytest.raises(CriteriaError):
        load_criteria(p)


def test_loader_rejects_missing_with_value(tmp_path):
    def m(d):
        r = next(x for x in d["records"] if x["status"] == "미확보")
        r["min"] = 1
    with pytest.raises(CriteriaError):
        load_criteria(_write(tmp_path, m))
