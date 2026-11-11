# 모듈 라이브러리 (티켓 07)

검증을 통과한 분석 코드를 저장하고, 비슷한 작업에서 재사용·수정·신규 중 하나를 고른다.

## 켜는 방법
`analysis/tasks._library(ctx)`가 `ctx.modules`(ModuleStore) 또는 환경변수 `JEJU_MODULE_STORE`(폴더 경로, `1`/`on`이면 기본 `module_store/`)가 있을 때만 켠다. 둘 다 없으면 기존 동작 그대로다 (API 서버에서 켜려면 `ctx.modules` 연결 또는 환경변수 설정이 필요하고, 러너/API는 07 소유가 아니라 연결하지 않았다).

## 저장소 (`module_store/<id>/v<N>/`)
`module.py`(코드), `meta.json`(Module.meta()), `cache.pkl`(결과 캐시 1칸). 메타: id, version, status(`auto`/`verified`), title, description, tags, input_roles, output_schema(`[{id,kind,columns[{name,dtype,unit}]}]`, 순서가 출력 순서), params, validation(mock·real), tested_on(`[{dataset_id, version_hash}]`), model, created, goal(개인정보 제거), code_hash.
- 새 id = `<제목 slug>-<코드 해시 6자>`. **수정**으로 만든 코드는 기반이 `auto`면 같은 id의 다음 버전, 기반이 `verified`면 새 id.
- 같은 코드(ast 정규화 해시)가 이미 있으면 새로 저장하지 않고 `tested_on`만 보탠다.
- 단일 사용자 가정. 버전 디렉터리를 `mkdir`로 선점하고 파일은 임시 파일 + `os.replace`로 써서, 같은 id 동시 저장이 서로 덮어쓰지 않게만 한다 (잠금 없음, 캐시 파일 경쟁은 방치).

## 개인정보 제거 (`privacy.py`)
goal·title·description·tags에 `scrub()` 적용: 이메일, 전화, 제주 부근 좌표 소수, `api_key/serviceKey/token/secret/password=값`, `sk-…`, 32자 이상 토큰, 지번 주소, `이름: 홍길동`, `성+이름+씨/님/농장주/조합장/사장`. 코드에 좌표·키 리터럴이 있으면 **저장하지 않는다**. 한계: 호칭 없는 사람 이름은 못 잡는다. 역할 매핑·실제 컬럼 이름은 저장하지 않는다.

## 검색 (`search.py`)
작업 제목+설명과 모듈 제목+설명+태그의 유사도(기본 `NgramRetriever`: 글자 2·3-gram TF-IDF 코사인, 네트워크 없음) + 조건: 출력 개수 일치, 모듈의 입력 역할(dtype)을 채울 작업 입력이 있어야 후보. 점수 = 유사도 + 0.15(verified) + 0.05×role_hint 일치율. 임베딩으로 바꾸려면 `Retriever.scores(query, docs)`를 구현해 `ModuleStore(retriever=...)`에 넘긴다.

## 결정과 검증 (tasks.py)
후보가 있으면 LLM 호출 1회(`module_decision`)로 `reuse/revise/new` + `input_binding`({모듈 입력 이름: 작업 입력 id}) + `role_mapping`(모듈 입력 이름 기준)을 받는다. 후보가 없으면 호출 없이 신규.
- **reuse**: 모듈 코드를 모듈 입력 이름으로 실행(mock -> 실데이터 + check, 설계는 모듈의 `output_schema` 기준, 출력은 순서대로 작업의 출력 id로 바뀜). **검증은 항상 다시 돈다.** 실패하면 그 모듈 코드와 실패 이유를 참고 자료로 넘겨 **수정**(1차 생성)으로 넘어가고, 이어서 기존 2차 수정 1회 규칙을 쓴다 (코드 생성 시도는 합쳐 최대 2회). 재사용 시도는 `attempts`에 `n=0, kind="reuse"`.
- **revise**: `REVISE_SYSTEM` + 참고 모듈 코드로 1차 생성. 통과하면 새 버전 저장. **new**: 기존 코드 생성.
- 결과 캐시: 캐시 키 = (모듈 id·버전, 연결, 매핑, **입력 데이터 버전 해시**). 키가 같으면 **mock까지만 다시 돌리고 실데이터 실행은 건너뛴다**(`attempts[].phase == "cache"`). 데이터 해시가 바뀌면 키가 달라져 캐시를 버리고 새 데이터로 실데이터 검증까지 다시 한다.
- `task["module"]`: `{decision, candidates, module_id, version, status, reuse_failed?, cache?, saved?}`.

## verified 시드 규칙
`backend/jejuagent/modules_seed/<영역>/*.py` 한 파일 = 모듈 하나 (`market/` 는 07, `site/` 는 12). `modules_seed/` 루트에는 파일을 두지 않고 `_` 로 시작하는 파일은 무시한다. 파일은 코드 계약(`MANIFEST`/`run`/`check`)을 지키며, MANIFEST에 선택 키 `id`(기본: 파일 이름), `version`(기본 1), `verified_by`(사람 검토 표시), `output_schema`(위 형식)를 쓴다. **파일을 두면 `ModuleStore`가 자동으로 읽는다** (등록 코드 없음). 계약 위반 파일이 있으면 `ModuleStore`가 `ValueError`를 낸다. 시드는 읽기 전용이고 `module_store/`로 복사되지 않는다 (결과 캐시만 `module_store/<id>/v<N>/cache.pkl`).

탑재: `market-price-trend-volatility`(입력 `trade{date,variety,price}`, 출력 `variety_trend_stats`·`variety_daily_price`), `market-catalog-explorer`(입력 `catalog` = `modules_lib.catalog_summary_table(registry.catalog())`, 출력 `catalog_overview`·`catalog_counts`). `verified_by` 값은 아직 사람 검토 전 표시다.

## 알려진 한계
- 카탈로그 요약 표는 아직 파이프라인의 데이터셋이 아니라서(③ 로드는 카탈로그 id만 읽음) 단계 ④에서 자동으로 입력되지 않는다. 직접 `catalog_summary_table()`로 만들어 쓴다.
- reuse는 작업 출력 개수 = 모듈 출력 개수일 때만 후보가 된다. 작업 설계(출력)는 모듈 검색 전에 정해지므로 컬럼 이름이 설계와 달라도 모듈 스키마를 따른다.
- 모듈 `params`는 아직 항상 `{}`로 실행한다.
