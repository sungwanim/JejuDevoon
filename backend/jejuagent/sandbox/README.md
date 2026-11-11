# 생성 코드 실행기 (sandbox)

LLM이 만든 분석 코드를 정적 검사하고, 별도 프로세스에서 실행해 출력을 검증한다. Runner에 의존하지 않는다.

> **한계 (먼저 읽을 것).** 이것은 **LLM 실수를 막는 장치**이지 악의적 코드를 막는 보안 샌드박스가 아니다.
> 정적 검사는 AST 이름 매칭이라 `getattr` 등으로 우회할 수 있고, 네트워크·쓰기 차단은 자식 프로세스 안의
> 파이썬 훅이라 `_socket`·`os.open`·ctypes로 우회할 수 있다. 메모리·CPU 제한은 없다 (시간 제한만).
> 파일 읽기는 막지 않는다. 신뢰할 수 없는 코드를 실행하지 말 것.

## 공개 함수

```python
from jejuagent.sandbox import run_generated_code
r = run_generated_code(code, inputs, params, *, profiles=None, artifacts=None, role_mapping=None,
                       value_ranges=None, timeout_s=60.0, mock_rows=None, seed=0)
```

- 입력: `code`(문자열), `inputs`(입력 이름 -> DataFrame), `params`(dict).
- mock: `inputs=None, profiles={입력 이름: Profile}`이면 Profile로 가짜 데이터를 만들어 같은 코드를 실행한다 (`r.details["mock"] is True`).
- `artifacts`: 설계한 중간산출물 `[{"id","kind","columns":[{"name","dtype"}]}]`. `kind`는 `table|series|geo`(DataFrame) 또는 `metrics`(dict). dtype은 `float|int|str|date|bool`. 없으면 `MANIFEST["outputs"]`의 id만 비교한다.
- `role_mapping`: `{입력 이름: {역할: 실제 컬럼}}`. 매핑된 컬럼만 골라 **역할 이름으로 바꿔** 코드에 넘긴다. 없으면 입력을 그대로 넘긴다.
- `value_ranges`: `{출력 컬럼: (최소, 최대)}` 상식 범위 검사(선택).
- 예외를 던지지 않고 항상 `SandboxResult`를 돌려준다:
  `ok`, `outputs`(중간산출물 사전), `failure`(분류 값), `message`, `problems`(check()·스키마·공통 검사·정적 위반 목록),
  `stage`(`static|contract|inputs|run|schema|check|common|done`), `elapsed_s`, `stdout`, `details`(`available_columns`, `traceback`, `error_type`, `mock`).
- 개발·테스트용 `extra_allowed_imports`, `extra_sys_paths`(예: `jejukit` 위치), `work_dir`.

## 코드 계약 (티켓 06이 이대로 생성한다)

```python
MANIFEST = {   # 반드시 리터럴 dict (함수 호출·변수 참조 금지)
    "title": "...", "description": "검색용 설명", "tags": ["price"],
    "input_roles": {"prices": {"date": "date", "variety": "str", "price": "float"}},
    "params": {"months": "int"},
    "outputs": ["price_trend", "volatility"],
}
def run(inputs, params) -> dict:      # inputs[입력 이름]의 컬럼은 역할 이름. 반환: {중간산출물 id: DataFrame | dict}
def check(outputs, inputs) -> list[str]:   # 문제 목록. 빈 리스트면 통과 (check에는 run이 건드리지 않은 새 입력이 간다)
```

- `MANIFEST["input_roles"]`의 입력·역할 컬럼이 없으면 실행 전에 `column_role_mismatch`.
- 데이터 문제는 코드에서 `raise DataProblem("이유")`로 알릴 수 있다 (import 없이 쓰는 builtin).
- 허용 import: `pandas numpy scipy math statistics datetime json re collections itertools functools typing calendar decimal fractions copy operator dataclasses numbers jejukit`. 상세: `static_check.ALLOWED_IMPORTS`.
- 금지: `eval exec compile __import__ input breakpoint exit quit`, `os.system/popen`, `subprocess.* socket.* shutil.* urllib.* requests.*`, `__subclasses__ __globals__ __builtins__`, 작업 폴더 밖(절대·`..`) 경로 쓰기 리터럴.

## 검증 순서와 실패 분류 (`failure` 값)

정적 검사(문법 -> 금지 -> 계약) -> 입력 준비(mock 생성·역할 매핑) -> 별도 프로세스 실행 -> 출력 스키마 -> `check()` -> 공통 검사. 첫 실패에서 멈춘다.

| 값 | 언제 | 2차(agent-flow 표) |
|---|---|---|
| `column_role_mismatch` | `KeyError`, DataFrame에 없는 속성, 매핑 컬럼 없음, MANIFEST 입력·역할 없음 | 역할 매핑 재작성 (`details.available_columns`) |
| `format_error` | `ValueError/TypeError/OverflowError`(변환 실패 등), 출력 id·타입·컬럼 불일치, run/check 반환 형식 오류 | 최소 수정 |
| `forbidden` | 금지 import·호출, 네트워크 시도, 작업 폴더 밖 쓰기(런타임) | 허용 목록 붙여 수정 |
| `timeout` | 제한시간 초과 (프로세스 트리 강제 종료) | 벡터 연산·기간 축소 |
| `validation_failed` | `check()`가 문제 반환, 출력 전부 결측, 상식 범위 위반 | 실패 항목 + 요약 통계 |
| `data_problem` | 입력이 빔, `DataProblem`, 빈 시퀀스·`.iloc[0]` 범위 초과 등(메시지 휴리스틱), 출력이 비어 있음 | 2차 없이 작업 실패 |
| `syntax_error`, `contract_error` | 문법 오류, MANIFEST/run/check 누락·형식 오류 | (표에 없음. 06이 형식 오류처럼 최소 수정으로 처리 권장) |
| `runtime_error` | 위에 속하지 않는 예외 | (06이 결정) |

`data_problem`/`column_role_mismatch`의 예외 기반 분류는 예외 종류·메시지 휴리스틱이다. 오분류 가능성이 있다.

## 격리 구현 (코드 위치: `executor.py`, `worker.py`)

- 별도 프로세스 `python -I -X utf8 worker.py <임시 작업폴더>`. 입력은 pickle, 부모가 `communicate(timeout)`; 초과 시 Windows는 `taskkill /F /T`로 트리째 종료 (venv의 python.exe 런처 때문).
- 환경변수는 **허용 목록**(SYSTEMROOT, PATH 등)만 남기고 전부 제거. `OPENAI_API_KEY` 등은 자식에 없다. TEMP/TMP는 작업폴더.
- 네트워크: 실행 직전에 `socket.socket`(하위 클래스로 교체)·`create_connection`·`getaddrinfo` 등을 `SandboxViolation`으로 교체. 한계: `_socket` 직접 사용 등은 막지 못한다. OS 방화벽 수준의 차단이 아니다.
- 파일 쓰기: cwd=작업폴더, `builtins.open`/`io.open`을 교체해 쓰기 모드 경로가 작업폴더 밖이면 차단. 한계: `os.open`, ctypes 등은 막지 못한다. 작업폴더는 실행 후 삭제.
- 파일 읽기, 메모리, CPU 사용량은 제한하지 않는다.

## mock (`mock.py`)

Profile(DESIGN.md §2 ③ 형식: `n_rows`, `columns[name, dtype, null_pct(0~100 퍼센트), min, max, n_unique, samples]`)을 입력 스키마로 가정한다. 03이 만든 실제 Profile의 모양이 다르면 `mock.py`만 맞추면 된다.
반영: 컬럼 이름·타입, 결측률, [min, max] 범위(양끝 값 포함), 샘플 값(모두 포함), 문자열은 샘플 값 안에서만 선택. 기본 최대 200행, 시드 고정.
**mock은 오류와 형식 불일치만 잡고 계산의 정확성은 못 잡는다.** 컬럼 간 관계·분포는 반영하지 않는다.

## 테스트

`.venv\Scripts\python.exe -m pytest backend/tests/sandbox` (키·네트워크 불필요, 약 70초: 테스트마다 프로세스를 띄운다).
