# 06: 분석 단계 한 줄 관통 (가격 추세)

**What to build:** '월동무 최근 가격 추세 알려줘'를 물으면 Agent가 작업 목록을 세우고, 작업마다 코드를 생성해 검증하고, 실패하면 원인에 맞춰 한 번 수정하며, 중간산출물을 만든다. 모든 작업이 실패하면 `failed`. 단계 ④ 파일과 분석 패키지를 소유한다. 모듈 저장·재사용은 07의 일이므로 여기서는 코드가 한 번 쓰이고 버려져도 된다. 읽을 것: `.scratch/jeju-agri-agent/spec.md`의 ④ 분석, `docs/agent-flow.md`.

**Blocked by:** 01, 03, 05

**Status:** done

- [x] LLM이 하위 질문과 선택된 데이터로 **순서 있는 작업 목록**을 낸다. 각 작업은 어떤 중간산출물을 어떤 데이터(또는 앞 작업의 산출물)로 만드는지를 담고, 앞 작업의 산출물을 뒤 작업이 입력으로 쓸 수 있다. 재계획은 하지 않는다
- [x] LLM에는 스키마, Profile, 샘플 값, 고정 도구 목록만 주고 원본 행을 통째로 주지 않는다
- [x] 중간산출물 설계(id, 종류, 설명, 컬럼·타입·단위)를 먼저 정한 뒤 코드 계약에 맞는 코드를 생성한다. 입력은 **역할 이름**으로 받고 LLM이 낸 역할 매핑으로 실행 직전에 컬럼 이름을 바꿔 넣는다
- [x] 05의 실행기로 검증한다 (정적 검사 → mock → 실데이터 + 검증 함수, 첫 실패에서 중단)
- [x] 1차 실패 시 실패를 분류하고 원인별 재료로 **2차 수정을 1회만** 한다 (컬럼 불일치는 코드가 아니라 역할 매핑을 다시, 형식 오류는 샘플 값 첨부 등). 데이터 문제는 2차 없이 바로 작업 실패. 2차 코드가 1차와 같으면 실행하지 않고 작업 실패
- [x] 작업 실패는 무엇을 하려 했고 왜 실패했는지가 실행 기록과 결과에 남고 다음 작업으로 넘어간다. 모든 작업이 실패하면 `failed`, 일부면 `partial`
- [x] 시도마다 seed를 고정하고 `temperature=0`으로 재현된다
- [x] 상한: 작업별 코드 시도 2회, 실행당 LLM 호출 25회, 작업당 60초가 적용된다
- [x] 스냅샷의 허브 거래 데이터로 '월동무 최근 가격 추세' 요청이 종단 간 실행되어 중간산출물(표·시계열)이 나온다 (가짜 LLM이 코드를 돌려주는 자동 테스트 + 실제 GPT-4o로 한 번 손으로 확인 -- 실제 GPT-4o 확인은 키가 없어 하지 않았다)
- [x] 자동 테스트(Runner 경계): 1차 성공, 1차 실패 후 2차 성공, 2차도 실패, 2차가 1차와 동일, 데이터 문제 즉시 실패, 모든 작업 실패 → `failed`

## Comments

## Result

**만든 것** (`backend/jejuagent/analysis/`, `runner/stages/s4_analyze.py`, `backend/tests/analysis/`)
- `analysis/tasks.py`: `plan_tasks`(작업 목록 1회 호출), `run_task`(생성 -> 검증 -> 1회 수정), `code_hash`(ast 정규화 해시). `analysis/prompts.py`: **코드 계약 생성 프롬프트(`CODE_SYSTEM`/`CODE_CONTRACT`/`codegen_user`)**, 수정 프롬프트(`fix_user`, `FIX_SYSTEM`, `REMAP_SYSTEM`), JSON 스키마. `analysis/artifact.py`: `Artifact`. `analysis/jejukit.py`: `jejuagent.data` 함수 재내보내기(`parse_dates to_numeric filter_region resample join_on`). 샌드박스에는 `extra_sys_paths=tasks.SYS_PATHS`(= jejukit 폴더 + backend 폴더)로 넘긴다.
- 단계 ④: 작업 목록 -> 작업마다 `run_task`. 선택된 데이터가 없으면 그대로 통과(불가 판정은 ②의 몫), 선택했는데 전부 로드 실패면 `failed`.

**작업 목록 구조** (`state.tasks`, JSON 가능): `{id, title, description, inputs:[데이터셋 id | 앞 작업의 산출물 id], outputs:[{id, kind(table|series|metrics|geo), description, columns:[{name,dtype,unit,min,max}]}], status(ok|failed|not_run), attempts:[...], failure:{what,why,classification}|None, artifact_ids, code}`. 순서 있는 목록이고 재계획은 없다. 뒤 작업은 앞 작업의 DataFrame 산출물을 입력으로 쓸 수 있다(metrics는 입력 불가). `attempts[i]` = `{n, kind(generate|fix_code|remap), code_hash, role_mapping, code, ok, failure, sandbox_stage, phase(mock|real), message, problems, elapsed_s}`, 2차가 1차와 같으면 `{identical_to_first: True}`로 실행 없이 기록.

**중간산출물 구조** (`state.artifacts[id]` = `analysis.Artifact`): `id, kind, value(DataFrame|dict), description, columns, source_ids(입력 데이터·산출물 id), task_id, module_title(MANIFEST title), code_hash, code, role_mapping`. `shape`가 있어 `RunState.to_dict()`가 `<Artifact shape=...>` 요약으로 trace에 남기고, 값 자체는 trace에 저장되지 않는다. `Artifact.summary()`는 값 없는 JSON 요약. **07**은 `code/role_mapping/module_title/code_hash/source_ids`로 모듈을 저장하면 되고(MANIFEST는 `check_code(code)[2]`), **08**은 `value/kind/columns/description`을 참조한다.

**실패 처리 규칙** (`tasks.py` docstring과 같음)
- 검증: `run_generated_code`를 mock(Profile, `profiles=`) -> 실데이터 순으로 두 번 부른다(정적 검사·스키마·check·공통 검사는 실행기가 처리). mock이 `data_problem`이면 mock 데이터(샘플 값에 필터 값이 없는 경우 등) 탓일 수 있어 실데이터로 넘어간다. `value_ranges`는 설계의 컬럼 min/max에서 만든다.
- 수정은 1회: `column_role_mismatch`는 코드 유지·역할 매핑만 재요청(실제 컬럼 목록 첨부), `format_error`는 입력 샘플·Profile, `forbidden`은 허용 import 목록, `timeout`은 벡터 연산·기간 축소 지시, `validation_failed`는 문제 목록+출력 요약 통계, `syntax_error/contract_error/runtime_error`는 메시지·트레이스백·Profile을 붙여 최소 수정(형식 오류와 같은 처리). `data_problem`은 2차 없이 작업 실패. 2차의 (코드 해시, 매핑)이 1차와 같으면(주석·공백 제거 후) 실행하지 않고 작업 실패(`classification: identical_retry`). 입력 id가 없거나 앞 작업이 실패했으면 `invalid_input`으로 생성 호출 없이 실패.
- 작업 실패는 `state.unanswered`에 `{what, why, classification}`로 남고 다음 작업으로 간다. 모든 작업 실패(또는 작업 목록이 비어 있음) -> `state.finish("failed")`. 일부 실패는 종료 상태를 정하지 않는다(finish를 부르면 ⑤가 건너뛰어지므로). 러너 기본값/⑤(08)가 `unanswered`를 보고 `partial`로 만든다. 상한(`LimitExceeded`)은 그대로 올리고 남은 작업은 `not_run` + unanswered.
- 재현성: LLM 어댑터가 `temperature=0`·seed 고정, 샌드박스 `seed=0`. 작업당 60초는 샌드박스 **실행 1회당** 제한(`TASK_TIMEOUT_S`; mock과 실데이터가 각각 최대 60초). LLM 25회 상한은 러너가 적용(한 작업이 최대 2회, 계획 1회).

**테스트**: `.venv\Scripts\python.exe -m pytest backend/tests/analysis` 8개 통과(약 43초), `backend/tests/runner`, `catalog`, `data`와 합쳐 28개 통과. 시나리오: 1차 성공(+앞 작업 산출물을 입력으로, `jejukit` import), 1차 실패(validation) 후 2차 성공, 컬럼 불일치 -> 역할 매핑만 재요청, 2차도 실패 후 다음 작업 진행(`partial`), 2차가 1차와 동일(주석만 다름), 데이터 문제 즉시 실패, 모든 작업 실패 -> `failed`, LLM에 원본 행이 가지 않음. ①②는 가짜 단계로 대신하고 ③④는 실제 단계를 쓴다(02·04가 진행 중이라). 실제 GPT-4o 확인은 하지 않았다.

**알려진 한계**
- **mock은 오류와 형식 불일치만 잡고 계산의 정확성은 못 잡는다.** 컬럼 간 관계·분포는 mock에 없고, 이동평균 같은 값이 틀려도 통과한다. 정확성은 `check()`(LLM이 쓴 검증)와 상식 범위가 맡는데, 그 검증도 LLM이 쓴다.
- 코드 파라미터(`params`)는 항상 `{}`로 실행한다(기본값은 코드 안에). 모듈 재사용(07)에서 파라미터를 받게 되면 작업 스키마에 추가해야 한다.
- 작업 시간 상한은 실행 1회당 60초라 작업당 합계로는 최대 약 4분(2시도 x mock+실데이터)까지 갈 수 있다. 실행 전체 5분 상한이 최종 안전장치.
- 합성 스냅샷 샘플은 컬럼당 3~5개 값만 보여주므로 필터할 값(예: 품종 이름)이 샘플에 없을 수 있다. LLM이 목표 문장의 값을 쓰도록 프롬프트에 예시는 넣지 않았다.
- `classify_error`는 휴리스틱이라 오분류 가능(05 README 참고).
