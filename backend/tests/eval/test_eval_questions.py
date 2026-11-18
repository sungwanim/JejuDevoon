"""티켓 13: 질문 세트 스키마 검증."""
from collections import Counter

import pytest
from run_eval import QUESTIONS, load_questions

from jejuagent.runner.datasource import SnapshotRegistry
from jejuagent.runner.request_plan import out_of_range
from jejuagent.runner.state import STATUSES

QS = load_questions(QUESTIONS)
IDS = {e["id"] for e in SnapshotRegistry().catalog()}
EXPECT_KEYS = {"status", "output_format", "needs", "clarify", "must_include", "must_exclude", "infeasible",
               "synthetic_warning", "profit_guarantee"}


def test_count_and_distribution():
    assert 30 <= len(QS) <= 60
    assert len({q["id"] for q in QS}) == len(QS)
    cats = Counter(q["category"] for q in QS)
    assert set(cats) >= {"대표", "처음보는조합", "도메인밖", "수익보장", "범위밖좌표", "되묻기", "해상도함정", "데이터없음"}
    assert min(cats.values()) >= 3
    assert any(q["ambiguous"] for q in QS) and not all(q["ambiguous"] for q in QS)


@pytest.mark.parametrize("q", QS, ids=[q["id"] for q in QS])
def test_question_schema(q):
    assert {"id", "category", "question", "click", "expect", "ambiguous", "note"} <= set(q)
    assert q["question"].strip() and isinstance(q["ambiguous"], bool)
    ex = q["expect"]
    assert EXPECT_KEYS <= set(ex)
    assert ex["status"] in STATUSES and ex["output_format"] in (None, "map", "report", "visual")
    assert set(ex["must_include"]) <= IDS and set(ex["must_exclude"]) <= IDS
    assert not set(ex["must_include"]) & set(ex["must_exclude"])
    assert set(ex.get("auxiliary_only", [])) <= IDS
    assert set(ex["needs"] or {}) <= {"point_analysis", "time_series", "spatial_comparison"}
    assert ex["clarify"] == (ex["status"] == "clarify")
    if ex["status"] in ("answered", "partial"):
        assert ex["synthetic_warning"] is not None      # 결과가 나오는 질문은 합성 경고 여부가 정해져 있다
    if ex["status"] == "infeasible":
        assert not ex["must_include"]
    if q["click"]:
        assert set(q["click"]) == {"lat", "lon"}


def test_click_questions_cover_land_and_out_of_range():
    ok = [q for q in QS if q["click"] and out_of_range(**q["click"]) is None]
    bad = [q for q in QS if q["click"] and out_of_range(**q["click"])]
    assert ok and len(bad) >= 2
    assert all(q["expect"]["status"] == "infeasible" for q in bad)


def test_point_questions_without_click_expect_clarify():
    for q in QS:
        if (q["expect"]["needs"] or {}).get("point_analysis") and not q["click"] and q["expect"]["status"] != "infeasible":
            assert q["expect"]["status"] == "clarify", q["id"]
