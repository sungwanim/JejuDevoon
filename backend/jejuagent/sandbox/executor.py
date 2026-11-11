"""생성 코드 실행기의 공개 함수 `run_generated_code`. 계약·한계는 README.md 참고."""
from __future__ import annotations

import math
import os
import pickle
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
from pandas.api import types as pdt

from .mock import mock_inputs
from .static_check import check_code

# 실패 분류 값 (agent-flow.md '2차 수정 방법' 표와 대응)
COLUMN_ROLE_MISMATCH = "column_role_mismatch"  # 컬럼·역할 불일치 -> 역할 매핑 재작성
FORMAT_ERROR = "format_error"                  # 형식 오류(변환 실패, 출력 스키마 불일치) -> 최소 수정
FORBIDDEN = "forbidden"                        # 금지 import·호출·네트워크·폴더 밖 쓰기 -> 허용 목록 붙여 수정
TIMEOUT = "timeout"                            # 제한시간 초과 -> 벡터 연산·기간 축소
VALIDATION_FAILED = "validation_failed"        # check()·공통 검사가 문제를 반환 -> 최소 수정
DATA_PROBLEM = "data_problem"                  # 빈 데이터·필요 기간 없음 -> 2차 없이 작업 실패
SYNTAX_ERROR = "syntax_error"                  # 문법 오류
CONTRACT_ERROR = "contract_error"              # 코드 계약(MANIFEST/run/check) 위반
RUNTIME_ERROR = "runtime_error"                # 그 밖의 실행 중 예외

_ENV_KEEP = ("SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "PATH", "PATHEXT", "COMSPEC", "LANG", "LC_ALL")
_DATA_MSG = ("empty sequence", "empty dataframe", "empty series", "empty array", "empty data", "empty result",
             "is empty", "zero-size", "zero-length", "no data", "empty index", "empty list")


@dataclass
class SandboxResult:
    ok: bool
    outputs: dict = field(default_factory=dict)   # 중간산출물 사전 (성공 시 또는 검증 실패 시 있는 만큼)
    failure: str | None = None                    # 위 실패 분류 값. 성공이면 None
    message: str = ""                             # 사람이 읽는 요약
    problems: list[str] = field(default_factory=list)  # check()·스키마·공통 검사 문제 목록, 정적 검사 위반 목록
    stage: str = ""                               # static | contract | inputs | run | schema | check | common | done
    elapsed_s: float = 0.0
    stdout: str = ""
    details: dict = field(default_factory=dict)   # 예: available_columns, traceback, mock=True


def run_generated_code(
    code: str,
    inputs: dict[str, pd.DataFrame] | None = None,
    params: dict | None = None,
    *,
    profiles: dict[str, dict] | None = None,
    artifacts: list[dict] | None = None,
    role_mapping: dict[str, dict[str, str]] | None = None,
    value_ranges: dict[str, tuple[float, float]] | None = None,
    timeout_s: float = 60.0,
    mock_rows: int | None = None,
    seed: int = 0,
    extra_allowed_imports=(),
    extra_sys_paths=(),
    work_dir: str | None = None,
) -> SandboxResult:
    """코드 문자열을 정적 검사하고 별도 프로세스에서 실행해 출력을 검증한다. 예외를 던지지 않는다.

    inputs        입력 이름 -> DataFrame (실데이터). None이고 profiles가 있으면 mock 모드.
    profiles      입력 이름 -> Profile dict. mock 데이터 생성에 쓴다.
    artifacts     설계한 중간산출물 [{"id","kind","columns":[{"name","dtype"}]}]. 없으면 MANIFEST["outputs"] id만 비교.
    role_mapping  입력 이름 -> {역할: 실제 컬럼명}. 있으면 매핑된 컬럼만 골라 역할 이름으로 바꿔 넘긴다.
    value_ranges  출력 컬럼 이름 -> (최소, 최대). 벗어난 값이 있으면 검증 실패 (카탈로그 단위 상식 범위).
    timeout_s     제한시간(초). 초과 시 프로세스 트리를 강제 종료하고 'timeout'.
    extra_allowed_imports  개발·테스트용 import 허용 추가분.
    """
    t0 = time.perf_counter()

    def done(**kw) -> SandboxResult:
        kw.setdefault("elapsed_s", round(time.perf_counter() - t0, 3))
        return SandboxResult(**kw)

    # 1) 정적 검사 (문법 -> 금지 -> 계약)
    kind, msgs, manifest = check_code(code, extra_allowed_imports)
    if kind:
        failure = {"syntax": SYNTAX_ERROR, "forbidden": FORBIDDEN, "contract": CONTRACT_ERROR}[kind]
        return done(ok=False, failure=failure, stage="contract" if kind == "contract" else "static",
                    message=msgs[0], problems=msgs)

    # 2) 입력 준비 (mock 생성, 역할 매핑, 데이터 문제)
    is_mock = inputs is None
    if is_mock:
        if profiles is None:
            return done(ok=False, failure=DATA_PROBLEM, stage="inputs", message="inputs도 profiles도 없다")
        inputs = mock_inputs(profiles, n_rows=mock_rows, seed=seed)
    try:
        inputs = _apply_roles(inputs, role_mapping, manifest["input_roles"])
    except _RoleError as e:
        return done(ok=False, failure=COLUMN_ROLE_MISMATCH, stage="inputs", message=str(e),
                    details={"available_columns": e.available, "mock": is_mock})
    empty = [k for k, df in inputs.items() if len(df) == 0]
    if empty:
        return done(ok=False, failure=DATA_PROBLEM, stage="inputs", details={"mock": is_mock},
                    message=f"입력 데이터가 비어 있다: {empty}")

    # 3) 별도 프로세스 실행
    res = _run_child(code, inputs, params or {}, timeout_s, extra_sys_paths, work_dir)
    stdout = res.get("stdout", "")
    base = dict(stdout=stdout, details={"mock": is_mock})
    if res.get("timeout"):
        return done(ok=False, failure=TIMEOUT, stage="run", message=f"제한시간 {timeout_s:g}초 초과로 강제 종료", **base)
    if "error" in res and not res.get("ok"):
        err = res["error"]
        failure = classify_error(err)
        base["details"].update(error_type=err["type"], traceback=err.get("traceback", ""))
        return done(ok=False, failure=failure, stage="run", message=f"{err['type']}: {err['message']}",
                    **base)

    outputs, problems = res["outputs"], res["problems"]
    # 4) 출력 스키마 -> check() -> 공통 검사
    schema_problems = check_schema(outputs, artifacts, manifest["outputs"])
    if schema_problems:
        return done(ok=False, outputs=outputs, failure=FORMAT_ERROR, stage="schema", message=schema_problems[0],
                    problems=schema_problems, **base)
    if problems:
        return done(ok=False, outputs=outputs, failure=VALIDATION_FAILED, stage="check",
                    message=f"check()가 문제 {len(problems)}건을 반환", problems=problems, **base)
    failure, common = common_checks(outputs, value_ranges)
    if common:
        return done(ok=False, outputs=outputs, failure=failure, stage="common", message=common[0],
                    problems=common, **base)
    return done(ok=True, outputs=outputs, stage="done", **base)


# ---------------------------------------------------------------- 내부

class _RoleError(Exception):
    def __init__(self, msg, available):
        super().__init__(msg)
        self.available = available


def _apply_roles(inputs, role_mapping, input_roles):
    out = {}
    for name, df in inputs.items():
        m = (role_mapping or {}).get(name)
        if m is not None:
            missing = {role: col for role, col in m.items() if col not in df.columns}
            if missing:
                raise _RoleError(f"입력 '{name}'에 없는 컬럼으로 매핑됨: {missing}", {name: list(map(str, df.columns))})
            df = df[list(m.values())].rename(columns={col: role for role, col in m.items()})
        out[name] = df
    for name, roles in input_roles.items():
        if name not in out:
            raise _RoleError(f"MANIFEST가 요구하는 입력 '{name}'이 없다 (받은 입력: {list(out)})", {k: list(map(str, v.columns)) for k, v in out.items()})
        absent = [r for r in roles if r not in out[name].columns]
        if absent:
            raise _RoleError(f"입력 '{name}'에 역할 컬럼이 없다: {absent}", {name: list(map(str, out[name].columns))})
    return out


def _run_child(code, inputs, params, timeout_s, extra_sys_paths, work_dir) -> dict:
    workdir = tempfile.mkdtemp(prefix="jeju_sbx_", dir=work_dir)
    try:
        with open(os.path.join(workdir, "payload.pkl"), "wb") as f:
            pickle.dump({"code": code, "inputs": inputs, "params": params,
                         "extra_sys_paths": [str(p) for p in extra_sys_paths]}, f)
        # 비밀값 제거: 허용 목록 방식. 나머지 환경변수는 모두 버린다.
        env = {k: v for k, v in os.environ.items() if k.upper() in _ENV_KEEP}
        env.update(TEMP=workdir, TMP=workdir)
        worker = str(Path(__file__).with_name("worker.py"))
        proc = subprocess.Popen([sys.executable, "-I", "-X", "utf8", worker, workdir], cwd=workdir, env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL)
        try:
            _, stderr = proc.communicate(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            if os.name == "nt":  # venv의 python.exe는 런처라 자식 프로세스까지 함께 끊어야 한다
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
            proc.kill()
            proc.communicate()
            return {"timeout": True}
        rp = os.path.join(workdir, "result.pkl")
        if not os.path.exists(rp):
            tail = stderr.decode("utf-8", "replace")[-1500:]
            return {"ok": False, "error": {"type": "ProcessCrash", "mro": ["ProcessCrash"], "traceback": tail,
                                           "message": f"자식 프로세스가 결과 없이 종료됨 (종료 코드 {proc.returncode}): {tail[-300:]}"}}
        with open(rp, "rb") as f:
            return pickle.load(f)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def classify_error(err: dict) -> str:
    names, msg = err["mro"], err["message"].lower()
    if "SandboxViolation" in names:
        return FORBIDDEN
    if "DataProblem" in names or any(w in msg for w in _DATA_MSG) \
            or ("IndexError" in names and ("out-of-bounds" in msg or "out of range" in msg)):
        return DATA_PROBLEM
    if "KeyError" in names or ("AttributeError" in names and "has no attribute" in msg and ("dataframe" in msg or "series" in msg)):
        return COLUMN_ROLE_MISMATCH
    if {"ValueError", "TypeError", "OverflowError"} & set(names):
        return FORMAT_ERROR
    return RUNTIME_ERROR


def _dtype_ok(s: pd.Series, dtype: str) -> bool:
    d = dtype.lower()
    if d in ("float", "double", "number"):
        return pdt.is_numeric_dtype(s) and not pdt.is_bool_dtype(s)
    if d in ("int", "integer"):
        return pdt.is_integer_dtype(s)
    if d in ("str", "string"):
        return pdt.is_string_dtype(s) or pdt.is_object_dtype(s)
    if d in ("date", "datetime", "timestamp"):
        return pdt.is_datetime64_any_dtype(s)
    if d in ("bool", "boolean"):
        return pdt.is_bool_dtype(s)
    return True


def check_schema(outputs: dict, artifacts: list[dict] | None, manifest_outputs: list[str]) -> list[str]:
    """출력 사전이 설계한 중간산출물(id, kind, 컬럼·타입)과 같은지. 문제 목록(빈 리스트면 일치)."""
    specs = {a["id"]: a for a in artifacts} if artifacts else {i: {"id": i} for i in manifest_outputs}
    out = []
    if set(outputs) != set(specs):
        out.append(f"출력 id 불일치: 기대 {sorted(specs)}, 실제 {sorted(map(str, outputs))}")
    for aid, spec in specs.items():
        if aid not in outputs:
            continue
        v, kind = outputs[aid], spec.get("kind")
        if kind in ("table", "series", "geo") and not isinstance(v, pd.DataFrame):
            out.append(f"'{aid}'({kind})은 DataFrame이어야 한다 (실제 {type(v).__name__})")
        elif kind == "metrics" and not isinstance(v, dict):
            out.append(f"'{aid}'(metrics)는 dict이어야 한다 (실제 {type(v).__name__})")
        elif isinstance(v, pd.DataFrame):
            for c in spec.get("columns", []):
                if c["name"] not in v.columns:
                    out.append(f"'{aid}'에 컬럼 '{c['name']}'이 없다 (실제 {list(map(str, v.columns))})")
                elif not _dtype_ok(v[c["name"]], c.get("dtype", "")):
                    out.append(f"'{aid}'.'{c['name']}' 타입 불일치: 기대 {c['dtype']}, 실제 {v[c['name']].dtype}")
    return out


def _missing(x) -> bool:
    return x is None or (isinstance(x, float) and math.isnan(x)) or x is pd.NA or x is pd.NaT


def common_checks(outputs: dict, value_ranges=None) -> tuple[str | None, list[str]]:
    """공통 검사. 빈 결과는 data_problem(필터 후 빈 데이터), 전부 결측·범위 위반은 validation_failed."""
    empty, bad = [], []
    for aid, v in outputs.items():
        if isinstance(v, pd.DataFrame):
            if v.empty:
                empty.append(f"'{aid}'가 비어 있다")
            elif v.isna().all().all():
                bad.append(f"'{aid}'의 값이 전부 결측이다")
            for col, (lo, hi) in (value_ranges or {}).items():
                if col in v.columns:
                    s = pd.to_numeric(v[col], errors="coerce")
                    n = int(((s < lo) | (s > hi)).sum())
                    if n:
                        bad.append(f"'{aid}'.'{col}'에 상식 범위 [{lo}, {hi}] 밖의 값이 {n}개 있다")
        elif isinstance(v, dict):
            if not v:
                empty.append(f"'{aid}'가 비어 있다")
            elif all(_missing(x) for x in v.values()):
                bad.append(f"'{aid}'의 값이 전부 결측이다")
    if empty:
        return DATA_PROBLEM, empty + bad
    if bad:
        return VALIDATION_FAILED, bad
    return None, []
