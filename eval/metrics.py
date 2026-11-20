"""평가 지표. 질문(정답 정보) + 결과 레코드(run_eval이 쓴 JSONL)로 계산한다. 정의는 docs/eval.md.

분모가 0인 지표는 value=None("해당 없음")이다. 0으로 바꾸지 않는다.
`ambiguous: true` 질문은 strict와 따로 집계한다.
"""
from __future__ import annotations

NEEDS_KEYS = ("point_analysis", "time_series", "spatial_comparison")


def rate(num: float, den: float) -> dict:
    return {"value": (num / den) if den else None, "num": num, "den": den}


def check_question(q: dict, r: dict) -> dict:
    """질문 하나의 검사 결과. 값: True/False, 정답 정보가 없어서 안 보는 항목은 None. include/exclude는 (맞은 수, 전체 수)."""
    ex = q["expect"]
    errored = r.get("status") in (None, "error")
    out: dict = {}
    out["status"] = None if ex.get("status") is None else r.get("status") == ex["status"]
    exp_needs, got_needs = ex.get("needs"), r.get("needs")
    out["needs"] = None if not exp_needs else bool(got_needs) and all(got_needs.get(k) == v for k, v in exp_needs.items())
    out["format"] = None if ex.get("output_format") is None else r.get("output_format") == ex["output_format"]
    out["clarify"] = None if ex.get("clarify") is None else (r.get("status") == "clarify") == ex["clarify"]
    sel = {s["dataset_id"]: s.get("role") for s in r.get("selected") or []}
    inc, exc = ex.get("must_include") or [], ex.get("must_exclude") or []
    out["include"] = (sum(d in sel for d in inc), len(inc))
    out["exclude"] = (sum(d not in sel for d in exc), len(exc))
    out["infeasible"] = None if ex.get("infeasible") is None else (r.get("status") == "infeasible") == ex["infeasible"]
    out["profit"] = None if not ex.get("profit_guarantee") else bool(r.get("profit_guarantee")) and bool(r.get("profit_notice"))
    aux = ex.get("auxiliary_only") or []
    out["granularity"] = None if not aux else all(sel.get(d) in (None, "auxiliary") for d in aux)
    if errored:  # 예외로 죽은 질문은 정답이 있는 항목을 모두 틀린 것으로 센다
        for k, v in out.items():
            if isinstance(v, bool):
                out[k] = False
        out["include"], out["exclude"] = (0, len(inc)), (0, len(exc))
    return out


def _task_stats(rows: list[dict]) -> dict:
    tasks = [t for r in rows if r.get("status") not in (None, "error") for t in r.get("tasks") or []]
    coded = [t for t in tasks if any(a["n"] >= 1 for a in t["attempts"])]    # 코드 생성/수정까지 간 작업 (재사용만으로 끝난 것 제외)
    attempts = [a for t in tasks for a in t["attempts"]]
    reached_real = [a for a in attempts if a.get("phase") in ("real", "cache")]
    return {
        "code_first": rate(sum(any(a["n"] == 1 and a["ok"] for a in t["attempts"]) for t in coded), len(coded)),
        "code_within2": rate(sum(t["status"] == "ok" for t in coded), len(coded)),
        "real_after_mock_fail": rate(sum(not a["ok"] for a in reached_real), len(reached_real)),
        "module_reuse": rate(sum((t.get("module") or {}).get("decision") == "reuse" and t["status"] == "ok" for t in tasks), len(tasks)),
    }


def compute(questions: list[dict], records: list[dict]) -> dict:
    """한 질문 집단의 지표. questions/records는 같은 id로 맞춘다 (결과가 없는 질문은 건너뛴다)."""
    by_id = {r["id"]: r for r in records}
    pairs = [(q, by_id[q["id"]]) for q in questions if q["id"] in by_id]
    rows = [r for _, r in pairs]
    ck = [check_question(q, r) for q, r in pairs]
    m: dict = {"n_questions": len(pairs)}

    def frac(name):
        vals = [c[name] for c in ck if c[name] is not None]
        return rate(sum(vals), len(vals))

    for k in ("status", "needs", "format", "clarify", "infeasible", "profit", "granularity"):
        m[k] = frac(k)
    parse = [all(v for v in (c["needs"], c["format"], c["clarify"]) if v is not None)
             for c in ck if any(c[k] is not None for k in ("needs", "format", "clarify"))]
    m["parse_all"] = rate(sum(parse), len(parse))
    m["include_recall"] = rate(sum(c["include"][0] for c in ck), sum(c["include"][1] for c in ck))
    m["exclude_accuracy"] = rate(sum(c["exclude"][0] for c in ck), sum(c["exclude"][1] for c in ck))
    m.update(_task_stats(rows))
    ok = [r for r in rows if r.get("status") not in (None, "error")]
    m["limit_hit"] = rate(sum(bool(r.get("limit_hit")) for r in ok), len(ok))
    with_html = [r for r in ok if r.get("html_len")]
    m["removed_runs"] = rate(sum(bool(r.get("removed_sentences")) for r in with_html), len(with_html))
    m["removed_per_run"] = {"value": (sum(len(r.get("removed_sentences") or []) for r in with_html) / len(with_html)) if with_html else None,
                            "num": sum(len(r.get("removed_sentences") or []) for r in with_html), "den": len(with_html)}
    m["errors"] = rate(sum(r.get("status") in (None, "error") for r in rows), len(rows))
    for k in ("llm_calls", "input_tokens", "output_tokens", "seconds", "cost_usd"):
        vals = [r[k] for r in rows if r.get(k) is not None]
        m[f"avg_{k}"] = {"value": (sum(vals) / len(vals)) if vals else None, "num": sum(vals), "den": len(vals)}
    return m


def compute_all(questions: list[dict], records: list[dict]) -> dict:
    strict = [q for q in questions if not q.get("ambiguous")]
    amb = [q for q in questions if q.get("ambiguous")]
    return {"strict": compute(strict, records), "ambiguous": compute(amb, records), "all": compute(questions, records)}


def mismatches(q: dict, r: dict) -> list[str]:
    """틀린 항목 이름 목록 (리포트의 실패 분류에 쓴다)."""
    c = check_question(q, r)
    bad = [k for k, v in c.items() if v is False]
    if c["include"][0] < c["include"][1]:
        bad.append("include")
    if c["exclude"][0] < c["exclude"][1]:
        bad.append("exclude")
    return bad
