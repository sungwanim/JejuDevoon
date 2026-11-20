"""결과 JSONL -> 사람이 읽는 마크다운 리포트.

    python eval/report.py eval/results/<폴더>      # 폴더 안에 report.md를 쓴다
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
for p in (EVAL_DIR.parent / "backend", EVAL_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import metrics  # noqa: E402

# (키, 이름, 형식, 설명)
ROWS = [
    ("parse_all", "규격화 정확도 (필요성격·형식·되묻기 모두 일치)", "pct", "정답이 있는 3항목이 전부 맞은 질문 비율"),
    ("needs", "- 필요한 성격(needs)", "pct", "지정한 키만 비교"),
    ("format", "- 산출물 형식", "pct", "map/report/visual"),
    ("clarify", "- 되묻기 판정", "pct", ""),
    ("status", "종료 상태 일치율", "pct", "answered/partial/clarify/infeasible"),
    ("include_recall", "데이터 선택 재현율", "pct", "반드시 포함할 데이터 중 선택된 비율(합산)"),
    ("exclude_accuracy", "데이터 제외 정확도", "pct", "반드시 제외할 데이터 중 선택되지 않은 비율(합산)"),
    ("infeasible", "불가 판정 정확도", "pct", "infeasible 여부 일치"),
    ("granularity", "해상도 함정 통과율", "pct", "도 전체 단위 데이터를 지점 분석의 주 데이터로 쓰지 않음"),
    ("profit", "수익 보장 요구 처리율", "pct", "판정하고 재구성 안내를 낸 비율"),
    ("code_first", "코드 1회 성공률", "pct", "코드 생성·수정까지 간 작업 중 1차 성공(모듈 재사용만으로 끝난 작업 제외)"),
    ("code_within2", "코드 2회 내 성공률", "pct", "같은 작업 집합에서 2회 안에 성공"),
    ("real_after_mock_fail", "mock 통과 후 실데이터 실패율", "pct", "실데이터 단계까지 간 시도 중 실패(근사: 실데이터 단계 실패 / 도달)"),
    ("module_reuse", "모듈 재사용 성공 비율", "pct", "전체 작업 중 재사용으로 성공"),
    ("removed_runs", "근거 없는 숫자 문장이 제거된 응답 비율", "pct", "HTML을 낸 실행 중 제거 문장이 1개 이상"),
    ("removed_per_run", "응답당 제거된 문장 수", "num", "전체 문장 수는 기록하지 않아 문장 단위 비율은 못 낸다"),
    ("limit_hit", "상한 도달 비율", "pct", "LLM 호출 25회 / 5분 상한"),
    ("errors", "실행 예외 비율", "pct", "도구 자체가 질문을 못 끝낸 경우"),
]
COST_ROWS = [("avg_llm_calls", "질문당 평균 LLM 호출 수", "num"), ("avg_input_tokens", "질문당 평균 입력 토큰", "num"),
             ("avg_output_tokens", "질문당 평균 출력 토큰", "num"), ("avg_seconds", "질문당 평균 소요(초)", "num"),
             ("avg_cost_usd", "질문당 평균 비용(USD, 어림)", "usd")]
TAG_LABEL = {"status": "종료 상태", "needs": "필요한 성격", "format": "산출물 형식", "clarify": "되묻기",
             "include": "필요 데이터 누락", "exclude": "제외할 데이터를 선택함", "infeasible": "불가 판정",
             "profit": "수익 보장 처리", "granularity": "해상도 함정"}


def fmt(m: dict, kind: str) -> str:
    v = m["value"]
    if v is None:
        return "해당 없음"
    if kind == "pct":
        return f"{v * 100:.1f}%"
    return f"${v:.4f}" if kind == "usd" else f"{v:,.1f}"


def _table(rows: list[tuple], metric: dict, cost=False) -> list[str]:
    out = ["| 지표 | 값 | 분자/분모 | 설명 |", "|---|---|---|---|"]
    for r in rows:
        k, name, kind = r[:3]
        m = metric[k]
        frac = "-" if m["den"] == 0 else (f"{m['num']:g}/{m['den']:g}" if kind == "pct" else f"합 {m['num']:g} / {m['den']:g}건")
        out.append(f"| {name} | {fmt(m, kind)} | {frac} | {r[3] if len(r) > 3 else ''} |")
    return out


def _expected_observed(tag: str, q: dict, r: dict) -> tuple[str, str]:
    ex = q["expect"]
    sel = [s["dataset_id"] for s in r.get("selected") or []]
    if tag == "status":
        return str(ex.get("status")), str(r.get("status"))
    if tag == "needs":
        return json.dumps(ex.get("needs"), ensure_ascii=False), json.dumps(r.get("needs"), ensure_ascii=False)
    if tag == "format":
        return str(ex.get("output_format")), str(r.get("output_format"))
    if tag == "clarify":
        return str(ex.get("clarify")), str(r.get("status") == "clarify")
    if tag == "include":
        return f"포함 {ex.get('must_include')}", f"선택 {sel}"
    if tag == "exclude":
        return f"제외 {ex.get('must_exclude')}", f"선택 {sel}"
    if tag == "infeasible":
        return str(ex.get("infeasible")), str(r.get("status") == "infeasible")
    if tag == "profit":
        return "판정+안내", f"판정 {r.get('profit_guarantee')}, 안내 {r.get('profit_notice')}"
    return f"보조로만 {ex.get('auxiliary_only')}", f"선택 {r.get('selected')}"


def _trace_summary(r: dict) -> list[str]:
    lines = []
    if r.get("error"):
        lines.append(f"- 실행 예외: `{r['error']}`")
    for e in r.get("stage_errors") or []:
        lines.append(f"- 단계 오류: `{e}`")
    if r.get("selected") or r.get("excluded"):
        lines.append("- 선택: " + (", ".join(f"{s['dataset_id']}({s.get('role')})" for s in r.get("selected") or []) or "없음"))
        lines.append("- 제외: " + (", ".join(f"{x['dataset_id']}[{x.get('reason_code')}/{x.get('by')}]" for x in r.get("excluded") or []) or "없음"))
    for t in r.get("tasks") or []:
        at = ", ".join(f"{a['n']}회({a.get('kind')}){'OK' if a['ok'] else 'X:' + str(a.get('failure'))}" for a in t["attempts"])
        mod = (t.get("module") or {}).get("decision", "-")
        lines.append(f"- 작업 `{t['id']}` {t['status']} (모듈 {mod}; 시도 {at or '없음'})" + (f" 실패: {t['failure']['why'][:120]}" if t.get("failure") else ""))
    for u in r.get("unanswered") or []:
        lines.append(f"- 미답변: {u['what']} - {u['why']}")
    if r.get("message"):
        lines.append(f"- 안내문: {r['message'][:160]}")
    return lines


def _mismatch_section(qs: list[dict], by_id: dict) -> list[str]:
    out, n = [], 0
    for q in qs:
        r = by_id.get(q["id"])
        if r is None:
            continue
        bad = metrics.mismatches(q, r)
        if not bad:
            continue
        n += 1
        out += [f"#### {q['id']} [{q['category']}] {q['question'].replace('|', '/')}",
                (f"클릭: {q['click']}  " if q.get("click") else "") + (f"메모: {q['note']}" if q.get("note") else ""),
                "", "| 항목 | 기대 | 관측 |", "|---|---|---|"]
        for t in dict.fromkeys(bad):
            e, o = _expected_observed(t, q, r)
            out.append(f"| {TAG_LABEL.get(t, t)} | {e} | {o} |")
        out += ["", *_trace_summary(r), ""]
    return out if n else ["불일치 없음.", ""]


def failure_counts(qs: list[dict], by_id: dict) -> tuple[Counter, Counter]:
    tags, code = Counter(), Counter()
    for q in qs:
        r = by_id.get(q["id"])
        if r is None:
            continue
        tags.update(set(metrics.mismatches(q, r)))
        if r.get("status") == "error":
            tags["실행 예외"] += 1
        for t in r.get("tasks") or []:
            code.update(a["failure"] for a in t["attempts"] if not a["ok"] and a.get("failure"))
            if t["status"] == "failed" and t.get("failure"):
                code["작업 실패: " + str(t["failure"].get("classification"))] += 1
    return tags, code


def crossval_markdown() -> list[str]:
    """지점 기온 교차검증(관측소 하나씩 빼기) 평균 절대 오차. 수집한 실데이터가 있어야 계산된다."""
    try:
        from jejuagent.geo.climate import estimate_site
        from jejuagent.runner.datasource import SnapshotRegistry
        aws = SnapshotRegistry().load("jeju_weather_daily")
        cv = estimate_site(aws, 33.30, 126.55)["cross_validation"]
    except Exception as e:  # DEM 파일 없음 등
        return [f"계산하지 못했습니다: {type(e).__name__}: {e}", ""]
    out = ["실데이터(jeju_weather_daily) 기준. 관측소가 농경지 위주(고도 18~208m)라 고지대 성능은 보장하지 않는다.", "",
           "| 방법 | 변수 | 일 평균 절대오차(℃) | 기간평균 절대오차(℃) | 관측소 수 |", "|---|---|---|---|---|"]
    for _, x in cv.iterrows():
        out.append(f"| {x['method']} | {x['variable']} | {x['mae_daily_c']:.2f} | {x['mae_period_mean_c']:.2f} | {int(x['n_stations'])} |")
    return out + [""]


def build_report(records: list[dict], questions: list[dict], meta: dict | None = None, crossval: list[str] | None = None) -> str:
    meta = meta or {}
    by_id = {r["id"]: r for r in records}
    qs = [q for q in questions if q["id"] in by_id]
    mm = metrics.compute_all(qs, records)
    L = ["# 평가 리포트", ""]
    if meta.get("dry_run"):
        L += ["> **드라이런(가짜 LLM)입니다.** 가짜 LLM은 정답 정보를 보고 답하므로 아래 지표는 모델 성능이 아니라 도구가 동작하는지의 확인용입니다.", ""]
    L += [f"- LLM: {meta.get('llm', '?')} / 모델: {meta.get('model', '?')} (temperature {meta.get('temperature', '?')}, seed {meta.get('seed', '?')})",
          f"- 실행: {meta.get('started', '?')} ~ {meta.get('finished', '?')}, 질문 {len(qs)}개 (질문 파일 {meta.get('questions_file', '?')} #{meta.get('questions_sha', '?')})",
          f"- 모듈 저장소: {'실행 전체 공유' if meta.get('shared_modules') else '질문마다 격리'}", ""]
    L += [f"## 1. 지표 (애매하지 않은 질문 {mm['strict']['n_questions']}개)", "", *_table(ROWS, mm["strict"]), ""]
    L += [f"## 2. 애매한 질문 지표 ({mm['ambiguous']['n_questions']}개, `ambiguous: true`)", "",
          "정답 자체가 논쟁의 여지가 있는 질문이라 따로 집계한다. 해석에 주의.", "", *_table(ROWS, mm["ambiguous"]), ""]
    L += ["## 3. 정답과 다른 질문", "", "### 3-1. 애매하지 않은 질문", "",
          *_mismatch_section([q for q in qs if not q.get("ambiguous")], by_id),
          "### 3-2. 애매한 질문", "", *_mismatch_section([q for q in qs if q.get("ambiguous")], by_id)]
    tags, code = failure_counts(qs, by_id)
    L += ["## 4. 실패 분류별 집계", "", "| 분류 | 질문 수 |", "|---|---|"]
    L += [f"| {TAG_LABEL.get(k, k)} | {v} |" for k, v in tags.most_common()] or ["| (없음) | 0 |"]
    L += ["", "코드 실행 실패 분류(시도 단위):", "", "| 분류 | 횟수 |", "|---|---|"]
    L += [f"| {k} | {v} |" for k, v in code.most_common()] or ["| (없음) | 0 |"]
    tot = {k: sum(r.get(k) or 0 for r in records) for k in ("llm_calls", "input_tokens", "output_tokens", "cost_usd", "seconds")}
    L += ["", "## 5. 비용·시간", "", *_table(COST_ROWS, mm["all"]), "",
          f"- 합계: LLM 호출 {tot['llm_calls']:g}회, 입력 {tot['input_tokens']:,.0f} / 출력 {tot['output_tokens']:,.0f} 토큰, "
          f"약 ${tot['cost_usd']:.2f}, 소요 {tot['seconds']:.0f}초",
          "- 비용은 토큰 수에 공개 단가(gpt-4o 입력 $2.50, 출력 $10.00 / 100만 토큰)를 곱한 어림값이다." + (" 가짜 LLM의 토큰 수는 글자 수로 어림한 값이다." if meta.get("dry_run") else ""),
          "", "## 6. 지점 기온 교차검증 오차", "", *(crossval if crossval is not None else crossval_markdown())]
    return "\n".join(L) + "\n"


def write_report(out_dir: Path, questions: list[dict] | None = None, crossval: list[str] | None = None) -> str:
    out_dir = Path(out_dir)
    if questions is None:
        from run_eval import load_questions
        questions = load_questions()
    records = [json.loads(x) for x in (out_dir / "results.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    mp = out_dir / "meta.json"
    text = build_report(records, questions, json.loads(mp.read_text(encoding="utf-8")) if mp.exists() else None, crossval)
    from run_eval import scrub
    text = scrub(text)      # 오류 문구에 키가 섞여 들어와도 리포트에는 남기지 않는다
    (out_dir / "report.md").write_text(text, encoding="utf-8")
    return text


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("results_dir")
    ap.add_argument("--questions")
    a = ap.parse_args()
    qs = None
    if a.questions:
        from run_eval import load_questions
        qs = load_questions(Path(a.questions))
    write_report(Path(a.results_dir), qs)
    print(Path(a.results_dir) / "report.md")
