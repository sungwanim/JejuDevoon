# 16: 통합 — 지점 기후를 파이프라인에 연결하고 종단 간 실행을 확인

**What to build:** 개별 티켓이 각자 끝났지만 아직 연결되지 않은 부분을 이어서, 사용자가 지도를 클릭하고 "여기에 월동무 어때?" 같은 질문을 하면 ① 규격화 → ② 데이터 선택(지점 기후 데이터 포함) → ③ 로드 → ④ 분석(지점 기후 모듈 + 시세 모듈) → ⑤ 렌더(지도 HTML)가 한 줄로 이어지게 한다. 12가 `catalog/` 항목을 넣지 못했고(03의 `len(r) == 3` 테스트 때문), 09의 `make_registry()`가 API에 연결되지 않았으며, 12의 한계 문구·지리 산출물이 08 렌더에 연결되지 않았다. 이 티켓은 그 연결과 종단 간 가짜 LLM 시나리오 테스트를 소유한다. 읽을 것: `.scratch/jeju-agri-agent/spec.md`, `docs/agent-flow.md`, `docs/climate.md`, 06·07·08·09·12의 `## Result`.

**Blocked by:** 07, 12

**Status:** done

- [x] 지점 기후용 카탈로그 항목(공간 단위 `관측소`)을 추가한다. 실데이터가 없으면 `synthetic: true`로 분명히 표시된 합성 관측소 스냅샷을 쓰고, 기존 `backend/tests/catalog`의 개수 단정 테스트는 새 상태에 맞게 고친다 (03 소유 테스트이므로 이 티켓이 수정을 소유하고 이유를 `## Result`에 적는다)
- [x] ② 데이터 선택이 지점 질문에서 지점 기후 데이터를 선택할 수 있고, 지점 데이터가 생겼으므로 더 이상 모든 지점 분석에 '지점 단위 분석 불가'가 붙지 않는다 (가짜 LLM 테스트)
- [x] ③ 로드·④ 분석 사이에서 지점 좌표의 DEM 고도(`geo.climate.site_inputs`)를 부모 프로세스가 미리 계산해 분석 입력에 넣는다. 바다·범위 밖이면 안내와 함께 범위 밖으로 끝난다
- [x] 12의 `site_climate` 모듈이 07의 모듈 라이브러리에서 `verified`로 검색·재사용되어, 지점 질문에서 LLM 코드 생성 없이 `site_markers`·`site_indicators`·`suitability`·`cross_validation` 산출물이 나온다
- [x] 08의 `map` 렌더가 `site_markers`(kind=geo)를 지도에 표시하고, 12의 한계 문구(`geo.climate.limitations`)와 합성 표시가 결과에 들어간다
- [x] 09의 `make_registry()`를 API 앱에 연결해 `JEJU_DATA_MODE=live`일 때 라이브/폴백이 동작하고, 폴백 안내(`registry.notices`)가 사용자에게 보인다. `api/`는 01 소유였으나 01은 끝났으므로 최소 수정만 한다
- [x] 종단 간 자동 테스트(가짜 LLM): ① 지도 클릭 + "월동무 어때?" → 지도 HTML과 적합도, ② 위치 없음 → 되묻기 후 이어짐, ③ 도메인 밖 → `infeasible`, ④ 제주시 지점 + 감귤 → 서귀포 데이터만 있다는 안내와 `partial`
- [x] `npm run build` 통과, 가능하면 개발 서버를 띄워 브라우저에서 위 ①을 한 번 확인한다 (자기가 띄운 서버만 포트의 PID로 종료)
- [x] 합성 데이터만으로 만든 결과에는 합성 경고가 항상 최상단에 나온다

## Comments

## Result

**방침 변경 반영(사용자 결정):** 공공데이터포털 + 제주데이터허브만 쓴다. 문헌 기반 적합도(12의 `suitability`/`criteria`)는 **기본 꺼짐**, `JEJU_SUITABILITY=1`일 때만 켠다(`geo.climate.suitability_enabled/criteria_for_pipeline`). 기본 상태의 결과에는 적합도 판정·문헌 출처가 없고, 한계 문구에 "재배 적합도는 공공데이터셋 근거가 없어 판정하지 않는다"가 들어간다. 그래서 수용 기준 중 "적합도(근거 출처 포함)"는 켰을 때만 성립하고(`test_suitability_is_opt_in`), 기본은 지점 기온 지표·고도·교차검증·합성 경고다. `criteria.json`, `criteria/` 코드는 수정하지 않았다.

**만든 것**
- 카탈로그 `catalog/synthetic_aws_daily.json`(공간 단위 `관측소`, `synthetic: true`, 제목·출처·notes에 합성 명시, 실데이터는 기상청 AWS 또는 농진청 농업기상 API로 대체 예정) + `snapshots/synthetic_aws_daily.json`(12개 관측소 x 365일, `geo.climate.synthetic_aws`, 재생성은 `python -m jejuagent.catalog.make_snapshots`). 로더가 표준 스키마로 읽고 `df.attrs["synthetic"]=True`. 개수 단정 테스트 3곳(catalog `len==3`/id 집합, modules 카탈로그 탐색 `==3`, selection enum 집합)을 4개 기준으로 고침(항목이 늘었기 때문).
- ②: `runner/selection.py` '지점 단위 분석 불가'는 이제 **선택된 데이터 중에** 관측소·격자 단위가 없을 때만 붙는다(카탈로그 전체 기준에서 변경). 요약에 `synthetic` 추가, 프롬프트에 지점 분석은 관측소 기후 데이터를 고르라는 한 줄.
- ③ `runner/stages/s3_load.py`: 지점 분석(점 좌표 + 관측소 데이터)이면 부모가 DEM 고도를 계산해 가상 입력 표 `site_point`(lat, lon, elevation_m)와 `crop_criteria`를 `state.data/profiles`에 더한다. 바다·범위 밖이면 `infeasible`(①이 먼저 거르므로 두 번째 안전장치). `state.extra["module_params"]={"synthetic":bool}`. 09 폴백(`df.attrs["data_mode"]=="fallback"`)은 원인·해결 방법을 `state.extra["notices"]`로(레지스트리 전체 `registry.notices`는 서버 수명 동안 쌓이므로 실행별로는 df.attrs를 썼다).
- ④ `analysis/tasks.py`: 모듈 재사용 시 모듈이 선언한 파라미터(`synthetic`)를 `module_params`에서 넘기고 캐시 키에 포함(06은 params를 항상 `{}`로 실행했다). `site_climate`는 verified로 검색·재사용되어 LLM 코드 생성 없이 `site_markers`(geo)·`site_indicators`·`suitability`·`cross_validation`·`limitations`가 나온다. 시세 모듈(`market-price-trend-volatility`)과 한 요청에서 두 작업이 나오는 시나리오도 확인.
- 모듈 소스 `modules_seed/site/site_climate.py`: 제목을 "지점 기후 추정"으로(적합도 문구 제거), `output_schema`(kind 포함) 추가, 한계 문구 LIMITATIONS에서 기준표·문헌 두 줄을 `CRITERIA_NOTES`(기준 행이 확보일 때만 포함)로 옮기고 "재배 적합도는 공공데이터셋 근거가 없어 판정하지 않는다." 추가. 격리 실행기가 빈 입력·빈 출력을 거부하므로 꺼진 상태의 `criteria`는 '미확보' 자리표시 한 행(적합도 표에는 "근거 부족" 한 줄)이다.
- ⑤ `render`: geo 산출물을 map 형식 맨 위 지도에 자동 표시(LLM이 빼도), 지점 모듈 결과가 있으면 `geo.climate.limitations(synthetic)` + 모듈의 limitations 표를 한계에 싣기, `state.extra["notices"]`를 안내 박스로 표시, metrics(dict) 산출물도 표 블록 허용, 한계 문구에서 "적합도는 참고용 기준 비교" 삭제. 합성 배너는 기존대로 제목 위 최상단(사용 데이터에 `synthetic`이 하나라도 있으면).
- 기타: `PROFIT_NOTICE`에서 "작목 적합도" -> "지점 기후 지표"(테스트 1곳 수정). `run_agent(..., modules=)`, `RunContext.modules`, `create_app(..., modules=)`. `api/main.py`는 `make_registry()`(`JEJU_DATA_MODE=live`면 LiveRegistry)와 `ModuleStore()`를 연결. `/api/runs/{id}/result`에 `notices` 추가(프런트 컴포넌트는 안 바꿈: 안내는 결과 HTML 안에 있음).
- 종단 간 테스트 `backend/tests/e2e/`(가짜 LLM은 `fakes.py`, system 문구로 단계 판별): ① 클릭 + 월동무 + 시세 -> 지도·고도·교차검증·시세 차트·합성 배너(제목 위)·한계 문구, 문헌 출처 없음, 코드 생성 호출 0회 ② 위치 없음 -> 되묻기 후 이어짐 ③ 도메인 밖 `infeasible`, 바다 클릭 `infeasible` ④ 제주시 + 감귤 -> 서귀포 데이터 제외 안내 + `partial` + 지점 기후 지도. 그 밖에 적합도를 켠 경우, 폴백 안내 표시, API 연결(`JEJU_DATA_MODE=live`).

**테스트:** `.venv\Scripts\python.exe -m pytest backend/tests -q` -> **192 passed** (약 196초). `npm run build` 통과. 브라우저 확인: `backend/`에서 `uvicorn demo_app:app --app-dir tests/e2e --port 8000` + `npm run dev`(5173)로 지도 클릭 + "여기에 월동무 어때? 최근 시세도 같이 알려줘" -> `answered`, 결과 iframe에 빨간 합성 배너가 최상단, 지도에 관측소·지점 마커, 지표 표가 나옴(모듈 저장소·runs는 임시 폴더). 띄운 서버는 포트(8000, 5173)의 PID로만 종료했다. `JEJU_LLM=fake` 기본 데모는 지점 시나리오를 못 흉내내므로 위 `tests/e2e/demo_app.py`를 쓴다.

**판단: 07의 캐시(같은 코드+같은 데이터 해시면 실데이터 실행 생략) 유지.** spec은 "데이터 버전 해시가 바뀌면 캐시를 버리고 재검증"이라고 해서 같은 해시면 캐시 사용을 전제하고, 재사용 때 mock 검증은 매번 돌며(결과는 결정적, seed 고정), 해시·파라미터·매핑이 바뀌면 전부 재검증한다. 단 캐시 적중 시 `check()`는 다시 안 돈다. 매번 `check()`까지 돌려야 한다면 `_try_reuse`에서 `cached`를 None으로 두면 된다.

**알려진 한계 / 연결하지 못했거나 미확인**
- 실제 GPT-4o로는 확인하지 못했다: ② 지점 질문에서 관측소 데이터 선택, ④ 작업 계획이 가상 입력(`site_point`, `crop_criteria`)을 쓰는지, 모듈 재사용 결정과 역할 매핑은 가짜 LLM으로만 검증했다. 실제 LLM이 가상 입력을 계획에 안 넣으면 재사용 후보가 안 잡혀 코드 생성으로 갈 수 있다(`site_climate`는 입력 3개가 모두 필요).
- 합성 관측소만 있다. 합성 진값이 6.5℃/km라 교차검증 오차는 실제 성능이 아니다. AWS 일자료 API 형식은 계속 미확인(09).
- 꺼진 상태에서도 적합도 표에는 '(없음) 재배 적합도 / 근거 부족' 자리표시 한 줄이 남는다(실행기 제약). LLM이 이 표를 보고서에 안 넣으면 보이지 않지만 fallback 렌더는 모든 산출물을 표로 보인다.
- 적합도를 켰을 때 작목 선택은 '작목 이름이 요청 crop 문자열에 포함'(월동무 -> 무)이라 거칠다.
- 라이브 모드(`JEJU_DATA_MODE=live`)는 키가 없어 폴백 안내 경로만 확인했다(가짜 레지스트리 + API import). 모듈 저장소 기본 위치 `module_store/`는 .gitignore에 없다.
- 브라우저에서는 지도·합성 배너만 눈으로 확인했고 차트(Chart.js)·흐름도(Mermaid)는 확인하지 않았다.

**13이 알아야 할 인터페이스**
- `run_agent(req, llm=, data=, click=, prev=, runs_dir=, modules=ModuleStore(...))`. 시드 모듈 id: `site_climate`(입력 `aws`,`site`,`criteria`), `market-price-trend-volatility`(`trade`), `market-catalog-explorer`.
- 지점 분석이면 `state.data`/`state.profiles`에 `site_point`, `crop_criteria`가 추가됨. `state.extra["module_params"]`(합성 여부), `state.extra["notices"]`(폴백 안내).
- 적합도 켜기: 환경변수 `JEJU_SUITABILITY=1`. 합성 여부는 카탈로그 `synthetic` 또는 `df.attrs["synthetic"]`.
- e2e용 가짜 LLM: `backend/tests/e2e/fakes.py`의 `respond(system, user)`/`make_llm()`(평가 도구가 재사용 가능).
