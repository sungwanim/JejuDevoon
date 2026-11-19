"""질문 세트 일괄 실행기. 사용법은 docs/eval.md.

    python eval/run_eval.py --llm fake --limit 5 --out eval/results/dry      # 드라이런 (가짜 LLM, 무료)
    python eval/run_eval.py --llm openai --limit 5                           # 소량 실제 실행 (OPENAI_API_KEY 필요)
    python eval/run_eval.py --llm openai                                     # 전체

Runner 경계(run_agent)를 그대로 쓰고 LLM만 바꾼다. 질문마다 격리된 임시 모듈 저장소를 쓴다(--shared-modules면 실행 전체가 하나).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
ROOT = EVAL_DIR.parent
for p in (ROOT / "backend", EVAL_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

QUESTIONS = EVAL_DIR / "questions.jsonl"
RESULTS = EVAL_DIR / "results"
# 대략적인 단가(USD / 100만 토큰). 공개 가격을 옮긴 값이라 바뀔 수 있다 -> 실제 청구액은 OpenAI 대시보드에서 확인.
PRICES = {"gpt-4o": (2.50, 10.00)}
USD_KRW = 1400
SECRET_ENV = ("OPENAI_API_KEY", "JEJU_HUB_PROJECT_KEY", "DATA_GO_KR_SERVICE_KEY")


def load_questions(path: Path = QUESTIONS) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def scrub(text: str) -> str:
    """결과 파일에 비밀값이 남지 않게 한다: 환경변수에 든 실제 값, sk- 형태의 키."""
    for name in SECRET_ENV:
        v = os.environ.get(name, "")
        if len(v) >= 6:
            text = text.replace(v, "***")
    return re.sub(r"sk-[A-Za-z0-9_\-*]+", "sk-***", text)


# ---------------------------------------------------------------- 비용 예상

def estimate(questions: list[dict], model: str = "gpt-4o") -> dict:
    """질문의 기대 경로로 호출 수·비용 범위를 어림한다. 낮은 쪽은 verified 모듈 재사용, 높은 쪽은 코드 생성·수정이 섞인 경우."""
    lo = hi = 0
    for q in questions:
        ex = q["expect"]
        if ex.get("status") == "clarify" or (q.get("click") and ex.get("status") == "infeasible"):
            lo += 1; hi += 1
        elif ex.get("status") == "infeasible":
            lo += 2; hi += 2
        else:                      # parse + select + plan + 모듈 결정 + 렌더 / 코드 생성·수정이 두 작업에 붙는 경우
            lo += 5; hi += 14
    pin, pout = PRICES.get(model, PRICES["gpt-4o"])

    def usd(calls, tin, tout):
        return calls * (tin * pin + tout * pout) / 1e6
    low, high = usd(lo, 2000, 300), usd(hi, 5000, 800)
    return {"questions": len(questions), "calls_low": lo, "calls_high": hi, "usd_low": low, "usd_high": high,
            "krw_low": low * USD_KRW, "krw_high": high * USD_KRW}


def format_estimate(e: dict, model: str) -> str:
    return (f"질문 {e['questions']}개, 예상 LLM 호출 {e['calls_low']}~{e['calls_high']}회\n"
            f"예상 비용 약 ${e['usd_low']:.2f} ~ ${e['usd_high']:.2f} (약 {e['krw_low']:,.0f}~{e['krw_high']:,.0f}원, {model} 공개 단가 기준 어림값)\n"
            "실제 청구액은 OpenAI 대시보드에서 확인하세요.")


# ---------------------------------------------------------------- 한 질문 실행

def _task_view(t: dict) -> dict:
    return {"id": t["id"], "title": t["title"], "status": t["status"], "failure": t.get("failure"), "module": t.get("module"),
            "attempts": [{k: a.get(k) for k in ("n", "kind", "ok", "failure", "phase", "message", "identical_to_first")}
                         for a in t.get("attempts", [])]}


def summarize(q: dict, res, seconds: float, model: str) -> dict:
    st, ev = res.state, res.events
    plan = st.plan or {}
    calls = [e for e in ev if e["type"] == "llm_call"]
    tin, tout = sum(e.get("input_tokens", 0) for e in calls), sum(e.get("output_tokens", 0) for e in calls)
    pin, pout = PRICES.get(model, PRICES["gpt-4o"])
    render = next((e for e in ev if e["type"] == "decision" and e.get("stage") == "s5_render"), {})
    from jejuagent.render import SYNTH_WARNING
    sel = st.selection or {}
    return {
        "id": q["id"], "category": q["category"], "status": res.status, "message": (res.message or "")[:300],
        "output_format": plan.get("output_format"), "needs": plan.get("needs"),
        "profit_guarantee": plan.get("profit_guarantee"), "profit_notice": bool(plan.get("notice")),
        "missing": plan.get("missing"),
        "selected": [{"dataset_id": s["dataset_id"], "role": s.get("role")} for s in sel.get("selected", [])],
        "excluded": [{k: x.get(k) for k in ("dataset_id", "reason_code", "by")} for x in sel.get("excluded", [])],
        "unanswered": [{"what": u.get("what"), "why": (u.get("why") or "")[:200]} for u in st.unanswered],
        "load_failures": st.load_failures, "needed_data": st.needed_data,
        "tasks": [_task_view(t) for t in st.tasks],
        "removed_sentences": (render.get("removed_sentences") or [])[:10], "render_fallback": render.get("fallback"),
        "html_len": len(res.html or ""), "synthetic_warning": bool(res.html and SYNTH_WARNING in res.html),
        "limit_hit": st.limit_hit, "llm_calls": len(calls), "input_tokens": tin, "output_tokens": tout,
        "cost_usd": round((tin * pin + tout * pout) / 1e6, 6), "llm_seconds": round(sum(e.get("ms", 0) for e in calls) / 1000, 2),
        "seconds": round(seconds, 2), "stage_errors": [f"{e.get('stage')}: {e.get('error')}" for e in ev if e["type"] == "error"],
        "error": None, "trace_dir": str(res.trace_path.parent.name) if res.trace_path else None,
    }


def error_record(q: dict, exc: BaseException, seconds: float) -> dict:
    return {"id": q["id"], "category": q["category"], "status": "error", "error": f"{type(exc).__name__}: {exc}", "message": "",
            "selected": [], "excluded": [], "tasks": [], "llm_calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0,
            "seconds": round(seconds, 2)}


def run_one(q: dict, llm, registry, store_dir: Path, runs_dir: Path, model: str) -> dict:
    from jejuagent.modules_lib import ModuleStore
    from jejuagent.runner import run_agent
    if hasattr(llm, "set_question"):
        llm.set_question(q)
    t0 = time.monotonic()
    try:
        res = run_agent(q["question"], llm=llm, data=registry, click=q.get("click"), runs_dir=runs_dir,
                        run_id=q["id"], modules=ModuleStore(store_dir))
        return summarize(q, res, time.monotonic() - t0, model)
    except Exception as e:  # 한 질문의 예외가 전체를 멈추지 않는다
        return error_record(q, e, time.monotonic() - t0)


# ---------------------------------------------------------------- CLI

def _no_key_message() -> str:
    return ("OPENAI_API_KEY를 찾지 못했습니다.\n"
            "  1) 프로젝트 루트의 .env.example을 .env로 복사하세요.\n"
            "  2) .env의 OPENAI_API_KEY= 뒤에 키를 붙여 넣으세요 (키를 채팅·커밋에 올리지 마세요).\n"
            "  3) 키 없이 도구만 확인하려면 --llm fake 로 드라이런을 돌리세요.")


def main(argv: list[str] | None = None, *, ask=input) -> int:
    ap = argparse.ArgumentParser(description="질문 세트 일괄 평가")
    ap.add_argument("--llm", choices=["openai", "fake"], required=True)
    ap.add_argument("--model", default="gpt-4o")
    ap.add_argument("--questions", default=str(QUESTIONS))
    ap.add_argument("--out", help="결과 폴더 (기본 eval/results/<타임스탬프>)")
    ap.add_argument("--limit", type=int, help="앞에서 N개만")
    ap.add_argument("--ids", help="쉼표로 구분한 질문 id만 (예: q01,q05)")
    ap.add_argument("--shared-modules", action="store_true", help="질문 사이에 모듈 저장소를 공유해 재사용 효과를 본다")
    ap.add_argument("--yes", action="store_true", help="비용 확인 없이 실행")
    ap.add_argument("--no-report", action="store_true")
    a = ap.parse_args(argv)

    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass
    qs = load_questions(Path(a.questions))
    if a.ids:
        want = set(a.ids.split(","))
        qs = [q for q in qs if q["id"] in want]
    if a.limit:
        qs = qs[:a.limit]
    if not qs:
        print("실행할 질문이 없습니다.")
        return 2

    from jejuagent.llm import OpenAILLM
    from jejuagent.runner.datasource import SnapshotRegistry
    if a.llm == "openai":
        if not os.environ.get("OPENAI_API_KEY"):
            print(_no_key_message())
            return 2
        llm = OpenAILLM(model=a.model)
    else:
        from fake_llm import ExpectationLLM
        llm = ExpectationLLM()

    est = estimate(qs, a.model)
    print(format_estimate(est, a.model) if a.llm == "openai" else f"드라이런(가짜 LLM): 질문 {len(qs)}개, 비용 없음")
    if a.llm == "openai" and not a.yes:
        try:
            ok = ask("계속할까요? [y/N] ").strip().lower() in ("y", "yes")
        except EOFError:
            ok = False
        if not ok:
            print("중단했습니다. (호출 0회)")
            return 1

    out = Path(a.out) if a.out else RESULTS / datetime.now().strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True, exist_ok=True)
    started = datetime.now().isoformat(timespec="seconds")
    tmp_root = Path(tempfile.mkdtemp(prefix="jeju-eval-modules-"))
    registry = SnapshotRegistry()
    records = []
    try:
        with (out / "results.jsonl").open("w", encoding="utf-8", newline="\n") as f:
            for i, q in enumerate(qs, 1):
                store = tmp_root / ("shared" if a.shared_modules else q["id"])
                rec = run_one(q, llm, registry, store, out / "traces", a.model)
                records.append(rec)
                f.write(scrub(json.dumps(rec, ensure_ascii=False, default=str)) + "\n")
                f.flush()
                print(scrub(f"[{i}/{len(qs)}] {q['id']} {rec['status']}  호출 {rec['llm_calls']}회  {rec['seconds']}초" + (f"  오류: {rec['error']}" if rec.get("error") else "")))
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)
    scrub_tree(out / "traces")
    from jejuagent.llm.openai_client import SEED
    meta = {"llm": a.llm, "model": a.model if a.llm == "openai" else "fake", "temperature": 0, "seed": SEED,
            "started": started, "finished": datetime.now().isoformat(timespec="seconds"), "n_questions": len(qs),
            "questions_file": Path(a.questions).name, "questions_sha": hashlib.sha256(Path(a.questions).read_bytes()).hexdigest()[:12],
            "shared_modules": a.shared_modules, "estimate": est, "dry_run": a.llm == "fake"}
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    if not a.no_report:
        from report import write_report
        write_report(out, qs)
        print(f"리포트: {out / 'report.md'}")
    print(f"결과: {out / 'results.jsonl'}")
    return 0


def scrub_tree(d: Path) -> None:
    """trace 파일에도 같은 비밀값 제거를 적용한다."""
    for p in d.rglob("*") if d.exists() else []:
        if p.is_file() and p.suffix in (".json", ".html"):
            t = p.read_text(encoding="utf-8")
            s = scrub(t)
            if s != t:
                p.write_text(s, encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
