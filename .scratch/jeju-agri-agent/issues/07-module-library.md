# 07: 모듈 라이브러리 (저장·검색·재사용·수정)

**What to build:** 검증을 통과한 분석 코드가 자동 저장되고, 비슷한 질문에서 Agent가 재사용·수정·신규 중 하나를 골라 쓴다. 데이터가 바뀌면 오래된 결과가 재사용되지 않는다. 대표 분석은 `verified` 모듈로 미리 탑재한다. 읽을 것: `.scratch/jeju-agri-agent/spec.md`의 '모듈 라이브러리'.

**Blocked by:** 06

**Status:** done

- [x] 검증을 통과한 코드가 `module_store/`에 모듈 id·버전별로 `auto` 상태로 저장된다. 메타데이터: 제목, 검색용 설명, 태그, 입력 역할, 출력 스키마, 파라미터, 검증 기록(mock·실데이터), 테스트한 데이터 id와 버전 해시, 생성 모델, 생성일, 원 요청 목표(개인정보 제거)
- [x] 작업 설명의 임베딩 유사도와 필요한 역할로 후보를 검색하고 `verified`를 `auto`보다 우선한다
- [x] LLM이 **재사용 / 수정 / 신규** 세 갈래 중 하나를 고르고 컬럼을 입력 역할에 매핑한다. 수정은 기존 모듈 코드를 참고 자료로 넘겨 새 버전을 만든다
- [x] **재사용해도 검증은 다시 돌린다**
- [x] 컬럼 이름이 다른 비슷한 데이터에 같은 모듈이 역할 매핑만 바꿔 재사용된다 (자동 테스트)
- [x] 데이터 버전 해시가 바뀌면 캐시된 결과는 버리고 코드는 재검증해서 쓴다
- [x] 대표 분석(품목별 가격 추세·변동성, 카탈로그 탐색)이 `verified` 모듈로 탑재되어 LLM 코드 생성 없이 스냅샷에서 재현된다
- [x] 자동 테스트(Runner 경계): 신규 → 저장 → 두 번째 비슷한 요청에서 재사용 후보로 선택, 수정 후 새 버전, 해시 변경 무효화, `verified` 우선

## Comments

## Result

**만든 것**: `backend/jejuagent/modules_lib/`(`store.py` 저장·버전·캐시, `search.py` 검색, `privacy.py` 개인정보 제거, `tables.py` 카탈로그 요약 표, `README.md` 규칙·한계 전부), `backend/jejuagent/modules_seed/market/`(verified 2개), `backend/tests/modules/`. `analysis/tasks.py`(`_library/_decide/_try_reuse/_saver`, `_verify`에 cached, `_success`에 콜백)와 `analysis/prompts.py`(DECISION/REVISE)를 최소 수정. 라이브러리는 `ctx.modules` 또는 환경변수 `JEJU_MODULE_STORE`가 있을 때만 켜지므로 라이브러리를 켜지 않으면 06 동작 그대로다.

**테스트**: `.venv\Scripts\python.exe -m pytest backend/tests/modules` 10개 통과(약 1분). modules + analysis + runner + catalog + data + selection 47개 통과. 시나리오: 신규 -> auto 저장(메타·개인정보 제거), 컬럼 이름이 다른 데이터(`priceMovingAverage`)에 역할 매핑만 바꿔 재사용(코드 생성 호출 없음, mock -> 실데이터 재검증), 재사용 실패 -> 수정 폴백, 수정 -> 같은 id v2, 데이터 해시 변경 시 캐시 폐기 + 재검증, verified > auto, 필요한 역할 못 채우면 후보 제외, 코드의 키 리터럴은 저장 거부, verified 가격 모듈이 스냅샷에서 LLM 코드 생성 없이 재현, 카탈로그 탐색 모듈이 카탈로그 요약 표에서 재현.

**결정(문서에 상세)**: 재사용 검증 실패 시 그 모듈을 참고 자료로 수정으로 넘어감. 캐시 키가 같으면 mock까지만 다시 돌리고 실데이터 실행은 생략(`phase: "cache"`), 해시가 바뀌면 캐시를 버리고 전부 재검증. 검색은 글자 n-gram TF-IDF(임베딩 API 호출 없음, `Retriever`로 교체 가능). 동시성은 단일 사용자 가정 + mkdir 선점/임시 파일 replace만.

**알려진 한계**: 러너/API(`ctx.modules` 주입)는 소유 밖이라 연결하지 않았다(환경변수로 켬). 카탈로그 요약 표는 파이프라인 데이터셋이 아니라 ④에서 자동 입력되지 않는다. reuse 후보는 출력 개수가 같을 때만. 사람 이름 제거는 호칭 휴리스틱. `verified_by`는 아직 사람이 검토하지 않았다. `module_store/`는 .gitignore에 없다(필요하면 사용자가 결정). 실제 GPT-4o로 reuse/revise 결정을 확인하지 않았다.

**12·13이 알아야 할 것**: 모듈 메타 형식은 `modules_lib.store.Module`(README 참고). verified 등록은 `modules_seed/<영역>/<이름>.py` 파일 추가만 하면 된다(MANIFEST 선택 키 `id`, `version`, `verified_by`, `output_schema`). 12의 `site/site_climate.py`는 이미 `ModuleStore()`가 읽는다. 평가(13)는 `ModuleStore(root, seed_dirs=[...], retriever=...)`로 격리된 저장소를 만들어 `ctx.modules`에 넣으면 된다. `state.tasks[i]["module"]`에 결정·후보·캐시·저장 id가 남는다.
