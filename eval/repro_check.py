"""재현성 검사: 기본 탑재(verified) 모듈과 스냅샷으로 같은 입력을 2번 실행해 중간산출물이 같은지 확인한다.

    python eval/repro_check.py [--n 4]

가짜 LLM(드라이런과 같은 것)을 쓰므로 키·비용이 없다. 질문 중 verified 모듈만으로 끝나는 것(지점 기후·가격·재배현황)을
골라 질문마다 새 모듈 저장소로 두 번 돌리고 중간산출물(표·dict)의 해시를 비교한다. LLM의 변동성은 이 검사가 보지 않는다
(그건 실제 GPT-4o 평가에서 같은 질문을 두 번 돌려 봐야 한다).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
for p in (EVAL_DIR.parent / "backend", EVAL_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

VERIFIED_ONLY = {"synthetic_aws_daily", "jdh_agri_daily_trade", "jeju_vegetable_cultivation"}   # verified 모듈이 있는 데이터셋


def artifact_hash(value) -> str:
    import pandas as pd
    if isinstance(value, pd.DataFrame):
        h = hashlib.sha256()
        h.update(json.dumps([list(value.columns), [str(t) for t in value.dtypes]]).encode())
        h.update(pd.util.hash_pandas_object(value.reset_index(drop=True), index=True).values.tobytes())
        return h.hexdigest()[:16]
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest()[:16]


def run_hashes(q: dict, store: Path) -> dict:
    from fake_llm import ExpectationLLM
    from jejuagent.modules_lib import ModuleStore
    from jejuagent.runner import run_agent
    from jejuagent.runner.datasource import SnapshotRegistry
    llm = ExpectationLLM()
    llm.set_question(q)
    res = run_agent(q["question"], llm=llm, data=SnapshotRegistry(), click=q.get("click"), runs_dir=None, modules=ModuleStore(store))
    return {"status": res.status, "artifacts": {k: artifact_hash(a.value) for k, a in sorted(res.state.artifacts.items())}}


def candidates(questions: list[dict]) -> list[dict]:
    return [q for q in questions if q["expect"].get("status") in ("answered", "partial") and q["expect"].get("must_include")
            and set(q["expect"]["must_include"]) <= VERIFIED_ONLY]


def check(questions: list[dict], n: int = 4) -> list[dict]:
    """질문별 {id, same, artifacts, a, b}. same=True이고 산출물이 하나 이상이어야 재현으로 본다."""
    out = []
    for q in candidates(questions)[:n]:
        with tempfile.TemporaryDirectory() as d:
            a, b = run_hashes(q, Path(d) / "a"), run_hashes(q, Path(d) / "b")
        out.append({"id": q["id"], "question": q["question"], "same": a == b and bool(a["artifacts"]),
                    "n_artifacts": len(a["artifacts"]), "a": a, "b": b})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=4)
    ap.add_argument("--questions")
    a = ap.parse_args(argv)
    from run_eval import QUESTIONS, load_questions
    rows = check(load_questions(Path(a.questions) if a.questions else QUESTIONS), a.n)
    for r in rows:
        print(f"{'재현됨' if r['same'] else '다름!'}  {r['id']} 산출물 {r['n_artifacts']}개  {r['question']}")
        if not r["same"]:
            print("  1회:", json.dumps(r["a"], ensure_ascii=False), "\n  2회:", json.dumps(r["b"], ensure_ascii=False))
    print(f"결과: {sum(r['same'] for r in rows)}/{len(rows)} 재현")
    return 0 if rows and all(r["same"] for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
