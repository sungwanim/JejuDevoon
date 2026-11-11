"""티켓 13: 일괄 실행기. 가짜 LLM 드라이런, 예외 격리, 비밀값, 비용 확인. 키·네트워크 없음."""
import json

import pytest
import repro_check
import report
import run_eval

QS = {q["id"]: q for q in run_eval.load_questions()}
FAST = "q03,q22,q33,q30"        # answered(verified 모듈) / 도메인 밖 / 되묻기 / 바다 클릭
KEY = "test-key"


@pytest.fixture(scope="module")
def dry(tmp_path_factory):
    out = tmp_path_factory.mktemp("dry") / "out"
    assert run_eval.main(["--llm", "fake", "--ids", FAST, "--out", str(out)]) == 0
    return out


def lines(out):
    return [json.loads(x) for x in (out / "results.jsonl").read_text(encoding="utf-8").splitlines()]


def test_dry_run_runs_to_the_end_and_writes_jsonl_meta_report(dry):
    recs = {r["id"]: r for r in lines(dry)}
    assert list(recs) == ["q03", "q22", "q30", "q33"]
    assert {i: r["status"] for i, r in recs.items()} == {"q03": "answered", "q22": "infeasible", "q33": "clarify", "q30": "infeasible"}
    r = recs["q03"]
    assert r["output_format"] == "report" and [s["dataset_id"] for s in r["selected"]] == ["jeju_vegetable_cultivation"]
    assert r["tasks"][0]["module"]["decision"] == "reuse" and r["llm_calls"] == 5 and r["input_tokens"] > 0
    assert r["excluded"] and all(x["dataset_id"] and x["reason_code"] for x in r["excluded"])
    meta = json.loads((dry / "meta.json").read_text(encoding="utf-8"))
    assert meta["dry_run"] and meta["temperature"] == 0 and meta["seed"] and meta["n_questions"] == 4
    text = (dry / "report.md").read_text(encoding="utf-8")
    assert "드라이런" in text and "## 1. 지표" in text and "합성 데이터 기준, 실제 성능 아님" in text
    assert (dry / "traces" / "q03" / "trace.json").exists()


def test_module_stores_are_isolated_per_question_and_deleted(tmp_path, monkeypatch):
    roots = []
    orig = run_eval.run_one

    def spy(q, llm, registry, store_dir, runs_dir, model):
        roots.append(store_dir)
        return orig(q, llm, registry, store_dir, runs_dir, model)
    monkeypatch.setattr(run_eval, "run_one", spy)
    run_eval.main(["--llm", "fake", "--ids", "q22,q33", "--out", str(tmp_path / "a"), "--no-report"])
    assert len(set(roots)) == 2 and not any(r.exists() for r in roots)
    roots.clear()
    run_eval.main(["--llm", "fake", "--ids", "q22,q33", "--out", str(tmp_path / "b"), "--no-report", "--shared-modules"])
    assert len(set(roots)) == 1


def test_one_question_exception_does_not_stop_the_run(tmp_path, monkeypatch):
    import jejuagent.runner as runner
    real = runner.run_agent

    def flaky(request, **kw):
        if "주식" in request:
            raise RuntimeError("boom")
        return real(request, **kw)
    monkeypatch.setattr(runner, "run_agent", flaky)
    out = tmp_path / "out"
    assert run_eval.main(["--llm", "fake", "--ids", "q22,q23,q33", "--out", str(out)]) == 0
    recs = {r["id"]: r for r in lines(out)}
    assert recs["q22"]["status"] == "error" and "RuntimeError: boom" in recs["q22"]["error"]
    assert recs["q23"]["status"] == "infeasible" and recs["q33"]["status"] == "clarify"
    text = (out / "report.md").read_text(encoding="utf-8")
    assert "실행 예외" in text and "RuntimeError: boom" in text


def test_secrets_never_reach_result_files(tmp_path, monkeypatch):
    import jejuagent.runner as runner
    monkeypatch.setenv("OPENAI_API_KEY", KEY)
    monkeypatch.setenv("JEJU_HUB_PROJECT_KEY", "test-hub-key")

    def leaky(request, **kw):
        raise RuntimeError(f"auth failed with {KEY} and test-hub-key")
    monkeypatch.setattr(runner, "run_agent", leaky)
    out = tmp_path / "out"
    run_eval.main(["--llm", "fake", "--ids", "q22", "--out", str(out)])
    blob = "".join(p.read_text(encoding="utf-8") for p in out.rglob("*") if p.is_file())
    assert "test-key" not in blob and "test-hub-key" not in blob and "***" in blob
    assert run_eval.scrub("키는 " + "sk" + "-abcdefghijklmnop 입니다") == "키는 sk-*** 입니다"


def test_missing_key_gives_korean_help_and_exit_2(tmp_path, capsys):
    out = tmp_path / "out"
    assert run_eval.main(["--llm", "openai", "--limit", "1", "--out", str(out)]) == 2
    msg = capsys.readouterr().out
    assert "OPENAI_API_KEY" in msg and ".env" in msg and "--llm fake" in msg and not out.exists()


def test_cost_estimate_is_printed_and_no_input_aborts(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("OPENAI_API_KEY", KEY)
    called = []

    def eof(prompt):
        called.append(prompt)
        raise EOFError
    out = tmp_path / "out"
    assert run_eval.main(["--llm", "openai", "--out", str(out)], ask=eof) == 1
    msg = capsys.readouterr().out
    assert called and "예상 LLM 호출" in msg and "예상 비용" in msg and "호출 0회" in msg and not out.exists()
    assert run_eval.main(["--llm", "openai", "--out", str(out)], ask=lambda p: "n") == 1


def test_estimate_scales_with_expected_paths():
    e = run_eval.estimate(list(QS.values()))
    assert e["questions"] == 44 and e["calls_low"] < e["calls_high"] and 0 < e["usd_low"] < e["usd_high"]
    assert run_eval.estimate([QS["q22"]])["calls_high"] == 1       # 도메인 밖은 호출 1회


def test_repro_check_with_verified_modules_is_identical(tmp_path):
    rows = repro_check.check([QS["q03"]], n=1)
    assert len(rows) == 1 and rows[0]["same"] and rows[0]["n_artifacts"] >= 3
    import pandas as pd
    assert repro_check.artifact_hash(pd.DataFrame({"a": [1]})) != repro_check.artifact_hash(pd.DataFrame({"a": [2]}))
    assert repro_check.candidates(list(QS.values()))      # 후보 질문이 있다


def test_report_cli_regenerates_from_results(dry, tmp_path):
    (dry / "report.md").unlink()
    report.write_report(dry, crossval=["(교차검증 생략)"])
    assert "(교차검증 생략)" in (dry / "report.md").read_text(encoding="utf-8")
