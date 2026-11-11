"""티켓 13: 지표 계산 단위 테스트. 작은 가짜 결과로 정확히 계산되는지, 분모 0이 '해당 없음(None)'인지."""
import metrics as M


def q(i, status="answered", amb=False, **ex):
    base = {"status": status, "output_format": None, "needs": None, "clarify": status == "clarify", "in_domain": None,
            "must_include": [], "must_exclude": [], "infeasible": status == "infeasible", "synthetic_warning": None,
            "profit_guarantee": False}
    return {"id": i, "category": "c", "question": i, "click": None, "expect": {**base, **ex}, "ambiguous": amb, "note": ""}


def r(i, status="answered", **kw):
    base = {"id": i, "status": status, "needs": {"point_analysis": False, "time_series": False, "spatial_comparison": False},
            "output_format": "report", "in_domain": True, "selected": [], "tasks": [], "llm_calls": 4, "input_tokens": 1000,
            "output_tokens": 100, "seconds": 2.0, "cost_usd": 0.01, "html_len": 100}
    return {**base, **kw}


def test_parse_and_selection_metrics():
    qs = [q("a", needs={"point_analysis": True}, output_format="map", in_domain=True, must_include=["D", "A"], must_exclude=["C"]),
          q("b", needs={"point_analysis": False}, output_format="report", in_domain=True, must_include=["E"], must_exclude=["C", "D"])]
    rs = [r("a", needs={"point_analysis": True, "time_series": True, "spatial_comparison": False}, output_format="map",
            selected=[{"dataset_id": "D", "role": "primary"}, {"dataset_id": "C", "role": "primary"}]),
          r("b", selected=[{"dataset_id": "E", "role": "primary"}])]
    m = M.compute(qs, rs)
    assert m["needs"] == {"value": 1.0, "num": 2, "den": 2}          # 지정하지 않은 time_series는 안 본다
    assert m["format"] == {"value": 1.0, "num": 2, "den": 2} and m["parse_all"] == {"value": 1.0, "num": 2, "den": 2}
    assert m["include_recall"] == {"value": 2 / 3, "num": 2, "den": 3}   # a는 A를 놓침
    assert m["exclude_accuracy"] == {"value": 2 / 3, "num": 2, "den": 3}  # a가 C를 선택함
    assert set(M.mismatches(qs[0], rs[0])) == {"include", "exclude"} and M.mismatches(qs[1], rs[1]) == []


def test_status_infeasible_clarify_and_synthetic():
    qs = [q("a", "infeasible"), q("b", "clarify"), q("c", "answered", synthetic_warning=True), q("d", "answered", synthetic_warning=False)]
    rs = [r("a", "infeasible"), r("b", "answered"), r("c", synthetic_warning=True), r("d", synthetic_warning=True)]
    m = M.compute(qs, rs)
    assert m["status"] == {"value": 0.75, "num": 3, "den": 4}                # b만 틀림
    assert m["infeasible"]["value"] == 1.0 and m["clarify"]["value"] == 0.75   # b는 되묻지 않음
    assert m["synthetic"] == {"value": 0.5, "num": 1, "den": 2}


def test_code_success_rates_and_real_failure():
    def t(status, attempts, module=None):
        return {"id": "t", "title": "t", "status": status, "failure": None, "module": module, "attempts": attempts}

    def a(n, ok, phase, failure=None):
        return {"n": n, "ok": ok, "phase": phase, "failure": failure}
    tasks = [t("ok", [a(1, True, "real")]),                                           # 1회 성공
             t("ok", [a(1, False, "mock", "format_error"), a(2, True, "real")]),      # 2회 성공
             t("failed", [a(1, False, "real", "validation_failed"), a(2, False, "real", "validation_failed")]),
             t("ok", [a(0, True, "cache")], {"decision": "reuse"})]                    # 재사용만
    m = M.compute([q("a")], [r("a", tasks=tasks)])
    assert m["code_first"] == {"value": 1 / 3, "num": 1, "den": 3}
    assert m["code_within2"] == {"value": 2 / 3, "num": 2, "den": 3}
    assert m["real_after_mock_fail"] == {"value": 2 / 5, "num": 2, "den": 5}
    assert m["module_reuse"] == {"value": 1 / 4, "num": 1, "den": 4}


def test_zero_denominators_are_not_applicable_not_zero():
    m = M.compute([q("a")], [r("a")])
    for k in ("needs", "format", "domain", "include_recall", "exclude_accuracy", "code_first", "code_within2",
              "real_after_mock_fail", "module_reuse", "synthetic", "profit", "granularity"):
        assert m[k]["value"] is None and m[k]["den"] == 0, k
    assert M.compute([], [])["status"]["value"] is None


def test_errored_runs_count_as_wrong_and_not_in_code_stats():
    qs = [q("a", needs={"point_analysis": True}, must_exclude=["C"], in_domain=True)]
    m = M.compute(qs, [{"id": "a", "status": "error", "error": "boom", "selected": [],
                        "tasks": [{"status": "ok", "attempts": [{"n": 1, "ok": True}]}]}])
    assert m["needs"]["value"] == 0.0 and m["domain"]["value"] == 0.0 and m["exclude_accuracy"]["value"] == 0.0
    assert m["errors"] == {"value": 1.0, "num": 1, "den": 1} and m["code_first"]["value"] is None


def test_removed_limit_granularity_and_profit():
    qs = [q("a", auxiliary_only=["E"]), q("b", profit_guarantee=True)]
    rs = [r("a", selected=[{"dataset_id": "E", "role": "primary"}], removed_sentences=["x", "y"], limit_hit="time"),
          r("b", profit_guarantee=True, profit_notice=True)]
    m = M.compute(qs, rs)
    assert m["granularity"]["value"] == 0.0 and m["profit"]["value"] == 1.0
    assert m["removed_runs"] == {"value": 0.5, "num": 1, "den": 2} and m["removed_per_run"]["value"] == 1.0
    assert m["limit_hit"]["value"] == 0.5 and m["avg_llm_calls"]["value"] == 4


def test_ambiguous_are_aggregated_separately():
    qs = [q("a"), q("b", amb=True)]
    rs = [r("a"), r("b", "failed")]
    m = M.compute_all(qs, rs)
    assert m["strict"]["status"]["value"] == 1.0 and m["ambiguous"]["status"]["value"] == 0.0
    assert m["all"]["status"]["value"] == 0.5 and m["strict"]["n_questions"] == m["ambiguous"]["n_questions"] == 1
