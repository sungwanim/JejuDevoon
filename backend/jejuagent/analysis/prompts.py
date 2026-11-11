"""LLM 프롬프트와 JSON 스키마. 코드 계약 생성 프롬프트는 CODE_SYSTEM / codegen_user() 에 있다.

LLM에게 주는 것: 스키마·Profile·샘플 값·고정 도구 목록·코드 계약뿐. 원본 행은 주지 않는다.
"""
from __future__ import annotations

import inspect
import json

from ..sandbox.static_check import ALLOWED_IMPORTS

DTYPES = ["float", "int", "str", "date", "bool"]
KINDS = ["table", "series", "metrics", "geo"]


def tool_list() -> str:
    from . import jejukit
    out = []
    for n in jejukit.__all__:
        f = getattr(jejukit, n)
        out.append(f"- jejukit.{n}{inspect.signature(f)}: {inspect.getdoc(f).splitlines()[0]}")
    return "\n".join(out)


def _j(x) -> str:
    return json.dumps(x, ensure_ascii=False, default=str)


# ---------------------------------------------------------------- 작업 목록

_COL = {"type": "object", "additionalProperties": False, "required": ["name", "dtype", "unit", "min", "max"],
        "properties": {"name": {"type": "string"}, "dtype": {"enum": DTYPES}, "unit": {"type": "string"},
                       "min": {"type": ["number", "null"]}, "max": {"type": ["number", "null"]}}}
_OUT = {"type": "object", "additionalProperties": False, "required": ["id", "kind", "description", "columns"],
        "properties": {"id": {"type": "string"}, "kind": {"enum": KINDS}, "description": {"type": "string"},
                       "columns": {"type": "array", "items": _COL}}}
TASKS_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["tasks"],
    "properties": {"tasks": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["id", "title", "description", "inputs", "outputs"],
        "properties": {"id": {"type": "string"}, "title": {"type": "string"}, "description": {"type": "string"},
                       "inputs": {"type": "array", "items": {"type": "string"}},
                       "outputs": {"type": "array", "items": _OUT}}}}},
}

PLAN_SYSTEM = """당신은 제주 농업 데이터 분석 Agent의 작업 계획자다.
하위 질문과 선택된 데이터로 **순서 있는 작업 목록**을 만든다. 규칙:
- 작업 하나는 '어떤 중간산출물을 어떤 데이터로 만드는가'다. inputs에는 선택된 데이터셋 id 또는 앞 작업이 만든 중간산출물 id만 쓴다.
- 앞 작업의 산출물(kind가 metrics가 아닌 것)을 뒤 작업의 입력으로 쓸 수 있다. 앞에서 만든 것만 쓴다. 재계획은 없다.
- 작업은 필요한 만큼만(보통 1~3개). 중간산출물 id는 영문 소문자 snake_case이고 전체에서 유일해야 한다.
- 중간산출물 설계: kind는 table|series|metrics|geo. table/series/geo는 표(컬럼 이름·dtype·단위를 모두 적는다), metrics는 dict(columns는 빈 목록).
  컬럼의 min/max는 단위 기준 상식 범위(모르면 null)다. 숫자 값을 꾸며내지 말고, 계산은 코드가 한다.
- 데이터에 없는 것을 요구하는 작업은 만들지 않는다.
도구(코드 생성 단계에서 import 가능한 고정 도구)는 참고용이다."""


def plan_user(plan: dict, selection: dict, profiles: dict) -> str:
    return (f"[목표]\n{(plan or {}).get('goal', '')}\n\n[하위 질문]\n{_j((plan or {}).get('sub_questions', []))}\n\n"
            f"[기간/작목/위치]\n{_j({k: (plan or {}).get(k) for k in ('period', 'crop', 'location')})}\n\n"
            f"[선택된 데이터]\n{_j((selection or {}).get('selected', []))}\n\n"
            f"[Profile (요약 통계와 샘플 값만, 원본 행 없음)]\n{_j(profiles)}\n\n[고정 도구]\n{tool_list()}")


# ---------------------------------------------------------------- 코드 생성

CODE_CONTRACT = f'''코드 계약 (반드시 지킨다):
```python
MANIFEST = {{   # 리터럴 dict만. 함수 호출·변수 참조 금지
    "title": "...", "description": "검색용 설명", "tags": ["price"],
    "input_roles": {{"<입력 이름>": {{"<역할>": "<dtype>", ...}}}},   # 입력 이름 = 입력 목록의 id 그대로
    "params": {{}},
    "outputs": ["<중간산출물 id>", ...],
}}
def run(inputs, params) -> dict:
    # inputs["<입력 이름>"]은 DataFrame이고 컬럼 이름은 '역할 이름'이다 (실제 컬럼 이름이 아님).
    return {{"<중간산출물 id>": DataFrame 또는 dict}}
def check(outputs, inputs) -> list[str]:
    # 문제 목록. 비어 있으면 통과. 빈 결과, 결측, 상식 밖 값을 검사한다. 입력은 건드리지 않은 상태로 온다.
```
- 허용 import: {", ".join(sorted(ALLOWED_IMPORTS - {"__future__"}))}. 그 밖은 금지(eval/exec/open 쓰기/네트워크 등).
- 입력 데이터가 비었거나 필요한 기간·값이 없으면 `raise DataProblem("이유")` (import 없이 쓰는 builtin).
- 출력 DataFrame은 설계한 컬럼 이름과 dtype(float|int|str|date|bool)을 정확히 지킨다. date는 datetime64.
- 행 단위 파이썬 루프 대신 pandas/numpy 벡터 연산을 쓴다. 결과는 결정적이어야 한다 (무작위 금지).
- role_mapping: 입력마다 {{역할: 실제 컬럼 이름}}. 실행 직전에 이 매핑으로 컬럼 이름이 역할 이름으로 바뀐다.
  실제 컬럼 이름은 Profile의 name을 그대로 쓴다. 코드는 실제 컬럼 이름을 쓰지 않고 역할 이름만 쓴다.'''

MAPPING_SCHEMA_PART = {"type": "array", "items": {
    "type": "object", "additionalProperties": False, "required": ["input", "role", "column"],
    "properties": {"input": {"type": "string"}, "role": {"type": "string"}, "column": {"type": "string"}}}}
CODE_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["role_mapping", "code"],
               "properties": {"role_mapping": MAPPING_SCHEMA_PART, "code": {"type": "string"}}}
MAPPING_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["role_mapping"],
                  "properties": {"role_mapping": MAPPING_SCHEMA_PART}}

CODE_SYSTEM = "당신은 pandas 분석 코드를 쓰는 데이터 엔지니어다. 코드 문자열 하나와 역할 매핑을 낸다.\n" + CODE_CONTRACT


def codegen_user(task: dict, input_profiles: dict) -> str:
    return (f"[작업] {task['title']}\n{task['description']}\n\n[입력 목록(입력 이름 = id)]\n{_j(task['inputs'])}\n\n"
            f"[입력 스키마와 Profile (샘플 값만)]\n{_j(input_profiles)}\n\n"
            f"[만들 중간산출물 설계]\n{_j(task['outputs'])}\n\n[고정 도구 (import jejukit)]\n{tool_list()}")


# ---------------------------------------------------------------- 2차 수정 (분류별 재료)

FIX_SYSTEM = ("당신은 실패한 분석 코드를 최소한으로 고치는 데이터 엔지니어다. 1차 코드와 실패 정보를 보고 "
              "고친 전체 코드와 역할 매핑을 낸다. 실패한 부분만 바꾸고 나머지는 유지한다.\n" + CODE_CONTRACT)
REMAP_SYSTEM = ("당신은 데이터 컬럼을 코드의 입력 역할에 매핑하는 데이터 엔지니어다. 코드는 바꾸지 않는다. "
                "실제 컬럼 목록을 보고 역할 매핑만 다시 낸다.")

_HEAD = "[작업] {title}\n{description}\n\n[1차 코드]\n```python\n{code}\n```\n\n[1차 역할 매핑]\n{mapping}\n\n"


def fix_user(task: dict, code: str, mapping: dict, failure: str, res, input_profiles: dict, out_stats) -> str:
    head = _HEAD.format(title=task["title"], description=task["description"], code=code, mapping=_j(mapping))
    fail = f"[실패 분류] {failure}\n[메시지] {res.message}\n"
    tb = (res.details or {}).get("traceback", "")
    if tb:
        fail += f"[트레이스백 끝부분]\n{tb[-1200:]}\n"
    if res.problems:
        fail += f"[문제 목록]\n{_j(res.problems[:10])}\n"
    extra = ""
    if failure == "column_role_mismatch":
        extra = (f"[실제 컬럼 목록]\n{_j((res.details or {}).get('available_columns', {}))}\n"
                 f"[입력 Profile]\n{_j(input_profiles)}\n역할 매핑만 다시 낸다.")
    elif failure == "format_error":
        extra = f"[입력 컬럼 샘플 값·Profile]\n{_j(input_profiles)}\n해당 컬럼의 변환과 출력 형식을 최소 수정한다."
    elif failure == "forbidden":
        extra = f"[허용 import 목록] {sorted(ALLOWED_IMPORTS)}\n금지 호출을 허용 목록 안의 것으로 바꾼다."
    elif failure == "timeout":
        extra = "제한시간을 넘겼다. 행 단위 루프를 벡터 연산으로 바꾸고, 필요하면 대상 기간을 줄인다."
    elif failure == "validation_failed":
        extra = f"[출력 요약 통계]\n{_j(out_stats)}\n실패한 항목이 통과하도록 최소 수정한다."
    else:  # syntax_error / contract_error / runtime_error
        extra = f"[입력 Profile]\n{_j(input_profiles)}\n오류를 최소 수정으로 고친다. 코드 계약을 다시 확인한다."
    return head + fail + extra


# ---------------------------------------------------------------- 모듈 라이브러리 (티켓 07)

DECISION_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["decision", "module_id", "reason", "input_binding", "role_mapping"],
    "properties": {
        "decision": {"enum": ["reuse", "revise", "new"]}, "module_id": {"type": "string"}, "reason": {"type": "string"},
        "input_binding": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["module_input", "task_input"],
            "properties": {"module_input": {"type": "string"}, "task_input": {"type": "string"}}}},
        "role_mapping": MAPPING_SCHEMA_PART,
    },
}

DECIDE_SYSTEM = """당신은 분석 작업에 기존 모듈을 쓸지 정하는 데이터 엔지니어다. 후보 모듈 목록과 작업을 보고 셋 중 하나를 고른다.
- reuse: 모듈이 작업을 그대로 해낸다. 컬럼 이름이 달라도 역할 매핑만 바꿔 쓴다. 출력 순서는 작업의 outputs 순서와 모듈 output_schema 순서가 대응한다.
- revise: 모듈이 비슷하지만 계산·필터·출력 컬럼을 바꿔야 한다. 모듈 코드는 참고 자료로 넘어가 새 버전이 만들어진다.
- new: 맞는 모듈이 없다. module_id는 빈 문자열.
reuse일 때: input_binding은 {모듈 입력 이름 -> 작업 입력 id}, role_mapping은 모듈 입력 이름마다 {역할: 입력 데이터의 실제 컬럼 이름}(Profile의 name 그대로)이다.
verified 모듈은 사람이 검토한 것이다. 맞으면 auto보다 우선한다. reuse/revise가 아니면 input_binding, role_mapping은 빈 배열."""


def decide_user(task: dict, input_profiles: dict, candidates) -> str:
    cands = [{"module_id": c.module.id, "version": c.module.version, "status": c.module.status, "title": c.module.title,
              "description": c.module.description, "tags": c.module.tags, "input_roles": c.module.input_roles,
              "output_schema": c.module.output_schema, "similarity": round(c.sim, 3), "suggested_binding": c.binding}
             for c in candidates]
    return (f"[작업] {task['title']}\n{task['description']}\n\n[입력 목록]\n{_j(task['inputs'])}\n\n"
            f"[입력 스키마와 Profile (샘플 값만)]\n{_j(input_profiles)}\n\n[만들 중간산출물 설계]\n{_j(task['outputs'])}\n\n"
            f"[후보 모듈]\n{_j(cands)}")


REVISE_SYSTEM = ("당신은 기존 분석 모듈을 참고해 새 작업에 맞게 고치는 데이터 엔지니어다. 참고 코드를 바탕으로 작업과 중간산출물 설계에 맞는 "
                 "전체 코드와 역할 매핑을 새로 낸다 (MANIFEST의 입력 이름·출력 id는 이번 작업의 것으로 바꾼다).\n" + CODE_CONTRACT)


def revise_user(task: dict, input_profiles: dict, base, reuse_failure: str | None) -> str:
    s = codegen_user(task, input_profiles) + (
        f"\n\n[참고 모듈 {base.id} v{base.version} ({base.status}) 코드]\n```python\n{base.code}\n```")
    if reuse_failure:
        s += f"\n\n[그대로 재사용했더니 실패]\n{reuse_failure}"
    return s
