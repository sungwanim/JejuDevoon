"""작업 계획과 작업 실행(코드 생성 -> 검증 -> 분류별 1회 수정). 재계획은 없다.

한 작업의 시도는 최대 2회: 1차 생성, 실패하면 분류별 재료로 2차 수정 1회.
 - column_role_mismatch: 코드는 그대로 두고 역할 매핑만 다시 (실제 컬럼 목록 제공)
 - format_error: 입력 컬럼 샘플·Profile 첨부  - forbidden: 허용 import 목록 첨부
 - timeout: 벡터 연산·기간 축소 지시  - validation_failed: 실패 항목 + 출력 요약 통계
 - syntax_error / contract_error / runtime_error: 메시지·트레이스백·Profile을 붙여 최소 수정 (형식 오류와 같은 처리)
 - data_problem: 2차 없이 작업 실패
 - 2차 (코드, 매핑)이 1차와 같으면 (ast 정규화 = 공백·주석 제거 후 해시) 실행하지 않고 작업 실패
"""
from __future__ import annotations

import ast
import dataclasses
import hashlib
import json
import os
import re
from pathlib import Path

import pandas as pd

from ..catalog.profile import profile as make_profile
from ..modules_lib import ModuleStore, search
from ..sandbox import SandboxResult, run_generated_code
from ..sandbox.static_check import check_code
from . import prompts
from .artifact import Artifact

STAGE = "s4_analyze"
SEED = 0
TASK_TIMEOUT_S = 60.0                    # 샌드박스 실행 1회당 제한시간
JEJUKIT_DIR = Path(__file__).resolve().parent          # `import jejukit` 이 풀리는 위치
BACKEND_DIR = JEJUKIT_DIR.parents[1]                   # jejukit이 `jejuagent.data`를 import 하려면 필요
SYS_PATHS = (str(JEJUKIT_DIR), str(BACKEND_DIR))


def code_hash(code: str) -> str:
    try:
        norm = ast.unparse(ast.parse(code))      # 주석·공백 차이가 사라진다
    except SyntaxError:
        norm = re.sub(r"#.*", "", code)
        norm = re.sub(r"\s+", "", norm)
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]


def _mapping(items: list[dict]) -> dict:
    m: dict = {}
    for it in items:
        m.setdefault(it["input"], {})[it["role"]] = it["column"]
    return m


# ---------------------------------------------------------------- 작업 목록

def plan_tasks(state, ctx) -> list[dict]:
    resp = ctx.llm.structured(prompts.PLAN_SYSTEM, prompts.plan_user(state.plan, state.selection, state.profiles),
                              prompts.TASKS_SCHEMA, schema_name="analysis_tasks", purpose="s4_plan_tasks")
    tasks = []
    for i, t in enumerate(resp.data.get("tasks", []), 1):
        tasks.append({**t, "id": t.get("id") or f"task{i}", "status": "pending", "attempts": [],
                      "failure": None, "artifact_ids": [], "code": None})
    return tasks


def _fail(task: dict, why: str, classification: str) -> None:
    task["status"] = "failed"
    task["failure"] = {"what": f"{task['title']}: {task['description']}", "why": why, "classification": classification}


# ---------------------------------------------------------------- 작업 실행

def run_task(task: dict, state, ctx) -> None:
    """task(dict)를 제자리에서 갱신하고 성공한 산출물은 state.artifacts에 넣는다. LimitExceeded는 그대로 올라간다."""
    inputs, profiles = {}, {}
    for name in task["inputs"]:
        if name in state.data:
            inputs[name], profiles[name] = state.data[name], state.profiles[name]
        elif name in state.artifacts and isinstance(state.artifacts[name].value, pd.DataFrame):
            inputs[name] = state.artifacts[name].value
            profiles[name] = make_profile(inputs[name], name, None)
        else:
            return _fail(task, f"입력 '{name}'을(를) 쓸 수 없다 (로드 실패, 앞 작업 실패, metrics 산출물, 또는 없는 id)",
                         "invalid_input")
    own = [o["id"] for o in task["outputs"]]
    dup = [o for o in own if o in state.artifacts]
    if not inputs or not own or dup:
        return _fail(task, f"작업 정의 오류 (입력 없음/출력 없음/출력 id 중복 {dup})", "invalid_task")

    designs = [{"id": o["id"], "kind": o["kind"],
                "columns": [{"name": c["name"], "dtype": c["dtype"]} for c in o["columns"]]} for o in task["outputs"]]
    ranges = {c["name"]: (c["min"], c["max"]) for o in task["outputs"] for c in o["columns"]
              if c.get("min") is not None and c.get("max") is not None}
    cx = dict(inputs=inputs, profiles=profiles, designs=designs, ranges=ranges)

    # --- 모듈 라이브러리 (켜져 있을 때만): 재사용 / 수정 / 신규. 재사용이 검증에서 실패하면 그 모듈을 참고해 수정(1차 생성)으로 넘어간다.
    lib, base, reuse_failure = _library(ctx), None, None
    if lib is not None:
        picked = _decide(task, ctx, lib, profiles)
        if picked and picked[0] == "reuse":
            done, reuse_failure = _try_reuse(task, state, ctx, lib, cx, *picked[1:])
            if done:
                return
            task["module"]["reuse_failed"] = reuse_failure
        if picked:
            base = picked[1]
    save = _saver(lib, task, state, ctx, cx, base) if lib is not None else None

    # --- 1차: 생성 (또는 수정)
    if base is not None:
        gen = ctx.llm.structured(prompts.REVISE_SYSTEM, prompts.revise_user(task, profiles, base, reuse_failure),
                                 prompts.CODE_SCHEMA, schema_name="analysis_code",
                                 purpose=f"s4_revise:{task['id']}").data
        kind1 = "revise"
    else:
        gen = ctx.llm.structured(prompts.CODE_SYSTEM, prompts.codegen_user(task, profiles), prompts.CODE_SCHEMA,
                                 schema_name="analysis_code", purpose=f"s4_codegen:{task['id']}").data
        kind1 = "generate"
    code, mapping = gen["code"], _mapping(gen["role_mapping"])
    res, phase = _verify(code, mapping, cx)
    sig1 = (code_hash(code), json.dumps(mapping, sort_keys=True))
    _log(task, ctx, 1, kind1, code, mapping, res, phase)
    if res.ok:
        return _success(task, state, code, mapping, res, save)
    if res.failure == "data_problem":
        return _fail(task, f"데이터 문제로 수정 없이 중단: {res.message}", res.failure)

    # --- 2차: 분류별 수정 1회
    kind = "remap" if res.failure == "column_role_mismatch" else "fix_code"
    stats = _out_stats(res.outputs) if res.failure == "validation_failed" else None
    user = prompts.fix_user(task, code, mapping, res.failure, res, profiles, stats)
    if kind == "remap":
        d = ctx.llm.structured(prompts.REMAP_SYSTEM, user, prompts.MAPPING_SCHEMA, schema_name="analysis_remap",
                               purpose=f"s4_remap:{task['id']}").data
        code2, mapping2 = code, _mapping(d["role_mapping"])
    else:
        d = ctx.llm.structured(prompts.FIX_SYSTEM, user, prompts.CODE_SCHEMA, schema_name="analysis_code",
                               purpose=f"s4_fix:{task['id']}").data
        code2, mapping2 = d["code"], _mapping(d["role_mapping"])
    if (code_hash(code2), json.dumps(mapping2, sort_keys=True)) == sig1:
        task["attempts"].append({"n": 2, "kind": kind, "code_hash": sig1[0], "role_mapping": mapping2,
                                 "identical_to_first": True, "ok": False, "failure": None,
                                 "message": "1차와 동일하여 실행하지 않음"})
        ctx.trace.add("decision", stage=STAGE, task_id=task["id"], attempt=2, identical_to_first=True)
        return _fail(task, f"2차 수정이 1차와 같아 실행하지 않음 (1차 실패: {res.failure}: {res.message})",
                     "identical_retry")
    res2, phase2 = _verify(code2, mapping2, cx)
    _log(task, ctx, 2, kind, code2, mapping2, res2, phase2)
    if res2.ok:
        return _success(task, state, code2, mapping2, res2, save)
    _fail(task, f"2차도 실패: {res2.failure}: {res2.message} (1차: {res.failure})", res2.failure)


def _verify(code, mapping, cx, cached=None):
    """정적 검사 -> mock -> 실데이터+check (순서는 실행기가 처리). mock이 data_problem이면 mock 데이터 탓일 수 있어 실데이터로 넘어간다.
    cached(같은 코드·같은 데이터 해시의 이전 결과)가 있으면 mock까지만 다시 돌리고 실데이터 실행은 건너뛴다."""
    kw = dict(artifacts=cx["designs"], role_mapping=mapping, value_ranges=cx["ranges"], timeout_s=TASK_TIMEOUT_S,
              seed=SEED, extra_sys_paths=SYS_PATHS)
    mock = run_generated_code(code, None, cx.get("params", {}), profiles=cx["profiles"], **kw)
    if not mock.ok and mock.failure != "data_problem":
        return mock, "mock"
    if cached is not None and mock.ok:
        return SandboxResult(ok=True, outputs=cached, stage="done"), "cache"
    return run_generated_code(code, cx["inputs"], cx.get("params", {}), **kw), "real"


def _log(task, ctx, n, kind, code, mapping, res, phase):
    rec = {"n": n, "kind": kind, "code_hash": code_hash(code), "role_mapping": mapping, "code": code,
           "ok": res.ok, "failure": res.failure, "sandbox_stage": res.stage, "phase": phase,
           "message": res.message, "problems": res.problems[:10], "elapsed_s": res.elapsed_s}
    task["attempts"].append(rec)
    ctx.trace.add("decision", stage=STAGE, task_id=task["id"], attempt=n, kind=kind, ok=res.ok,
                  failure=res.failure, phase=phase, message=res.message[:300], code_hash=rec["code_hash"])


def _success(task, state, code, mapping, res, on_ok=None, columns=None) -> None:
    manifest = check_code(code)[2] or {}
    h = code_hash(code)
    for o in task["outputs"]:
        cols = (columns or {}).get(o["id"]) or [{k: c[k] for k in ("name", "dtype", "unit")} for c in o["columns"]]
        state.artifacts[o["id"]] = Artifact(
            id=o["id"], kind=o["kind"], value=res.outputs[o["id"]], description=o["description"], columns=cols,
            source_ids=list(task["inputs"]), task_id=task["id"], module_title=manifest.get("title", ""),
            code_hash=h, code=code, role_mapping=mapping)
        task["artifact_ids"].append(o["id"])
    task["status"], task["code"] = "ok", code
    if on_ok:
        on_ok(code)


# ---------------------------------------------------------------- 모듈 라이브러리 연결 (티켓 07, modules_lib/README.md)

def _library(ctx):
    """ctx.modules(ModuleStore)가 있으면 그것, 없으면 환경변수 JEJU_MODULE_STORE(폴더 경로, 또는 1/on/true=기본 module_store/)가 있을 때만 켠다.
    둘 다 없으면 라이브러리를 쓰지 않는다 (기존 동작 그대로)."""
    lib = getattr(ctx, "modules", None)
    v = os.environ.get("JEJU_MODULE_STORE", "")
    if lib is None and v:
        lib = ModuleStore(None if v.lower() in ("1", "on", "true") else v)
    return lib


def _decide(task, ctx, lib, profiles):
    """후보 검색 -> (후보가 있으면) LLM이 재사용/수정/신규 선택. (kind, module, decision) 또는 신규면 None."""
    cands = search(lib, f"{task['title']} {task['description']}", profiles, n_outputs=len(task["outputs"]))
    task["module"] = {"decision": "new", "candidates": [(c.module.id, c.module.status, round(c.score, 3)) for c in cands]}
    if not cands:
        return None
    dec = ctx.llm.structured(prompts.DECIDE_SYSTEM, prompts.decide_user(task, profiles, cands), prompts.DECISION_SCHEMA,
                             schema_name="module_decision", purpose=f"s4_module_decision:{task['id']}").data
    m = next((c.module for c in cands if c.module.id == dec["module_id"]), None)
    kind = dec["decision"] if m is not None else "new"
    if kind != "new":
        task["module"].update(decision=kind, module_id=m.id, version=m.version, status=m.status)
    ctx.trace.add("decision", stage=STAGE, task_id=task["id"], module_decision=kind, module_id=m.id if m else None,
                  reason=dec.get("reason", "")[:300])
    return (kind, m, dec) if kind != "new" else None


def _try_reuse(task, state, ctx, lib, cx, m, dec):
    """모듈 코드를 그대로 쓰되 검증(mock -> 실데이터 + check)은 다시 돈다. (성공 여부, 실패 이유)."""
    binding = {b["module_input"]: b["task_input"] for b in dec["input_binding"]}
    mapping = _mapping(dec["role_mapping"])
    outs = [o["id"] for o in task["outputs"]]
    if (set(binding) != set(m.input_roles) or len(set(binding.values())) != len(binding)
            or any(t not in cx["inputs"] for t in binding.values()) or len(m.outputs) != len(outs)):
        return False, "입력 연결 또는 출력 개수가 모듈과 맞지 않는다"
    cx2 = dict(inputs={mi: cx["inputs"][ti] for mi, ti in binding.items()},
               profiles={mi: cx["profiles"][ti] for mi, ti in binding.items()},
               designs=[{"id": o["id"], "kind": o["kind"], "columns": o["columns"]} for o in m.output_schema],
               ranges=cx["ranges"],
               # 부모가 정한 파라미터(예: 합성 데이터 표시)는 모듈이 선언한 것만 넘긴다
               params={k: v for k, v in state.extra.get("module_params", {}).items() if k in m.params})
    tested = [{"dataset_id": n, "version_hash": p.get("version_hash", "")} for n, p in cx["profiles"].items()]
    # 캐시 키에 데이터 버전 해시가 들어 있어서, 데이터가 바뀌면 키가 달라져 이전 결과는 버려진다
    key = hashlib.sha256(json.dumps([m.id, m.version, binding, mapping, tested, cx2["params"]], sort_keys=True).encode()).hexdigest()
    cached = lib.cache_get(m, key)
    res, phase = _verify(m.code, mapping, cx2, cached)
    _log(task, ctx, 0, "reuse", m.code, mapping, res, phase)
    if not res.ok:
        return False, f"{phase} 검증 실패: {res.failure}: {res.message} {res.problems[:5]}"
    if cached is None:
        lib.cache_put(m, key, res.outputs)
    renamed = dataclasses.replace(res, outputs={t: res.outputs[mid] for mid, t in zip(m.outputs, outs)})
    cols = {t: [{k: c.get(k, "") for k in ("name", "dtype", "unit")} for c in o["columns"]]
            for t, o in zip(outs, m.output_schema)}
    by_task = {binding[mi]: mp for mi, mp in mapping.items()}
    _success(task, state, m.code, by_task, renamed, lambda code: lib.add_tested_on(m, tested), cols)
    task["module"]["cache"] = "hit" if cached is not None else "miss"
    return True, None


def _saver(lib, task, state, ctx, cx, base):
    """검증을 통과한 코드를 auto 모듈로 저장하는 콜백. 저장 실패(디스크 등)는 분석을 멈추지 않고 기록만 한다."""
    def save(code):
        try:
            m = lib.save(code, task=task, tested_on=[{"dataset_id": n, "version_hash": p.get("version_hash", "")}
                                                      for n, p in cx["profiles"].items()],
                         model=getattr(getattr(ctx.llm, "_inner", None), "model", ""),
                         goal=(state.plan or {}).get("goal", ""), base=base)
        except OSError as e:
            ctx.trace.add("decision", stage=STAGE, task_id=task["id"], module_save_failed=str(e))
            return
        if m is not None:
            task.setdefault("module", {})["saved"] = f"{m.id}@v{m.version}"
        ctx.trace.add("decision", stage=STAGE, task_id=task["id"], module_saved=f"{m.id}@v{m.version}" if m else None)
    return save


def _out_stats(outputs: dict) -> dict:
    s = {}
    for k, v in outputs.items():
        if isinstance(v, pd.DataFrame):
            num = v.select_dtypes("number")
            s[k] = {"shape": list(v.shape), "dtypes": {c: str(t) for c, t in v.dtypes.items()},
                    "nulls": {c: int(n) for c, n in v.isna().sum().items()},
                    "numeric": {c: {"min": float(num[c].min()), "max": float(num[c].max()), "mean": float(num[c].mean())}
                                for c in num.columns if num[c].notna().any()}}
        else:
            s[k] = {"type": type(v).__name__, "keys": list(v)[:20] if isinstance(v, dict) else None}
    return s
