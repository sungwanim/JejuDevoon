"""Agent Runner 경계 테스트: 가짜 LLM만 쓰고 키·네트워크 없이 통과한다."""
import json
import types

import pytest

from jejuagent.api.app import create_app
from jejuagent.llm import FakeLLM, LLMError, OpenAILLM
from jejuagent.runner import Limits, run_agent
from jejuagent.runner.pipeline import STAGES, Stage

IN = {}


def run(req, responses, tmp_path, **kw):
    llm = FakeLLM(responses)
    return run_agent(req, llm=llm, runs_dir=tmp_path, **kw), llm


def test_in_domain_passes_through_all_stages(tmp_path):
    res, _ = run("제주 월동무 가격 알려줘", [IN], tmp_path)
    assert res.status == "answered"
    assert [e["name"] for e in res.events if e["type"] == "stage"] == [s.name for s in STAGES]


def test_trace_saved_with_llm_call_info(tmp_path):
    res, llm = run("제주 월동무 가격 알려줘", [IN], tmp_path)
    saved = json.loads((tmp_path / res.state.run_id / "trace.json").read_text(encoding="utf-8"))
    assert saved["state"]["status"] == "answered"
    calls = [e for e in saved["events"] if e["type"] == "llm_call"]
    assert len(calls) >= 1
    assert {"model", "prompt_hash", "input_tokens", "output_tokens", "ms", "stage"} <= calls[0].keys()
    assert any(e["type"] == "transition" for e in saved["events"])


def test_fake_llm_records_calls_in_order():
    llm = FakeLLM([{"a": 1}, "안녕"])
    assert llm.structured("sys", "u1", {"type": "object"}, schema_name="x").data == {"a": 1}
    assert llm.text("sys", "u2").text == "안녕"
    assert [c["kind"] for c in llm.calls] == ["structured", "text"]
    assert llm.calls[0]["schema_name"] == "x" and llm.calls[1]["user"] == "u2"
    with pytest.raises(LLMError):
        llm.text("s", "u")  # 응답 소진


def test_llm_call_limit_ends_with_results_so_far(tmp_path):
    def chatty(state, ctx):
        for _ in range(5):
            ctx.llm.text("s", "u")
        return state
    stages = [Stage("s1_parse", types.SimpleNamespace(run=chatty)), *STAGES[1:]]
    res, llm = run("제주 감귤", ["x"] * 10, tmp_path, limits=Limits(max_llm_calls=3), stages=stages)
    assert len(llm.calls) == 3
    assert res.state.limit_hit == "llm_calls"
    assert res.status == "partial"
    assert [e["name"] for e in res.events if e["type"] == "stage"][-1] == "s5_render"  # 렌더로 건너뜀


def test_time_limit(tmp_path):
    res, llm = run("제주 감귤", [IN], tmp_path, limits=Limits(max_seconds=-1))
    assert res.state.limit_hit == "time" and res.status == "partial"
    assert llm.calls == []


def test_stage_exception_becomes_failed(tmp_path):
    def boom(state, ctx):
        raise LLMError("OPENAI_API_KEY가 없습니다")
    stages = [Stage("s1_parse", types.SimpleNamespace(run=boom))]
    res, _ = run("제주 감귤", [], tmp_path, stages=stages)
    assert res.status == "failed" and "OPENAI_API_KEY" in res.message
    assert any(e["type"] == "error" for e in res.events)


def test_openai_adapter_serialization_without_network():
    llm = OpenAILLM(client=object())
    kw = llm.build_kwargs("sys", "user", {"type": "object"}, "domain")
    assert kw["temperature"] == 0 and "seed" in kw and kw["model"] == "gpt-4o"
    assert kw["response_format"]["json_schema"]["strict"] is True
    assert "response_format" not in llm.build_kwargs("sys", "user")
    msg = types.SimpleNamespace(content='{"in_domain": false}', refusal=None)
    resp = types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)],
                                 usage=types.SimpleNamespace(prompt_tokens=7, completion_tokens=3))
    r = llm.parse_response(resp, "structured", "p", "h")
    assert r.data == {"in_domain": False} and (r.info.input_tokens, r.info.output_tokens) == (7, 3)


def test_openai_without_key_raises_llm_error(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(LLMError):
        OpenAILLM().text("s", "u")


def test_api_roundtrip(tmp_path):
    import time
    from fastapi.testclient import TestClient
    c = TestClient(create_app(lambda: FakeLLM([IN]), runs_dir=tmp_path))
    assert c.get("/api/catalog").json() == []
    rid = c.post("/api/runs", json={"request": "제주 월동무 가격 알려줘"}).json()["run_id"]
    for _ in range(50):
        st = c.get(f"/api/runs/{rid}").json()
        if not st["running"]:
            break
        time.sleep(0.05)
    assert st["status"] == "answered"
    full = c.get(f"/api/runs/{rid}/result").json()
    assert full["status"] == "answered" and full["events"]
    assert c.get("/api/runs/nope").status_code == 404


def test_openai_error_message_does_not_keep_masked_key_fragment():
    msg = "Error code: 401 - Incorrect API key provided: sk-ant-u*****************JAAA. You can find your API key"

    def boom(**kw):
        raise ValueError(msg)
    client = types.SimpleNamespace(chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=boom)))
    with pytest.raises(LLMError) as e:
        OpenAILLM(client=client).text("s", "u")
    assert "sk-***" in str(e.value) and "JAAA" not in str(e.value) and "ant-u" not in str(e.value)
