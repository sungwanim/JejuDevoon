# 17: 채소재배현황으로 작목별 면적당 조수입·재배면적 추세 분석

**What to build:** 사용자가 허브 데이터 `제주채소류재배현황.csv`(원본은 `data/` 폴더, 읽기 전용)로 "어떤 작목이 면적당 조수입이 높은지", "재배면적이 늘고 있는지"를 물으면, Agent가 이 데이터를 선택해 작목별 지표를 계산하고 결과를 보여준다. 이 데이터는 원칙(공공데이터포털 + 제주데이터허브) 안에서 "이익"에 가장 가까운 근거다. 한계를 반드시 표시한다: 도 전체 단위(지점 차이 설명 불가), 조수입 기준(비용 없음, 순이익 아님), 최신 연산이 20-21이고 데이터 기준일이 2021-08-09. 읽을 것: `docs/HANDOFF.md`의 5절, `.scratch/jeju-agri-agent/spec.md`, 03·07·16의 `## Result`.

**Blocked by:** None (can start immediately)

**Status:** done

- [x] 카탈로그 항목(허브 출처, 공간 단위 `도 전체`, 시간 단위 `연산(작기)`, 범위 15-16~20-21, 컬럼 이름·의미·단위(면적 ha, 생산량 톤, 조수입 백만원), 메모에 위 한계)이 추가되고 로더가 `연산` 값('20-21' 같은 작기 표기), 대분류(노지/시설), 소분류 28개 작목을 올바르게 읽는다. 인코딩은 utf-8-sig다
- [x] 기존 카탈로그 개수·id 집합을 단정하는 테스트(catalog, modules, selection)가 있으면 새 상태에 맞게 고친다 (16이 같은 방식으로 한 번 고쳤다)
- [x] 파생 지표를 코드 계약을 지키는 `verified` 모듈로 만든다 (`modules_seed/market/` 아래 새 파일): 작목별·연산별 면적당 조수입(백만원/ha), 수량(톤/ha), 단가(원/kg = 조수입(백만원)×1,000,000 ÷ 생산량(톤)×1,000), 재배면적 증감(최신 연산 대비 이전 연산, 6개 연산 추세), 작목 간 순위. 단위 변환을 모듈 안에서 명시하고 테스트로 검증한다 (예: 20-21 월동무 면적 5,056ha, 조수입 106,434백만원 → 21.05백만원/ha)
- [x] 노지/시설을 구분해 계산하고, 소분류 '기타(…)' 묶음 항목은 순위 비교에서 제외하거나 표시한다 (합계 성격의 항목이므로 개별 작목과 비교하면 오해를 부른다)
- [x] 작목 이름이 허브 가격 데이터(월동무, 구마늘 등)와 다를 때의 **매핑을 데이터 파일로** 두고, 데이터에서 확인되는 것만 연결한다(이름이 같은 것). 확신할 수 없는 매핑은 만들지 않고 `## Result`에 목록으로 적는다
- [x] ② 데이터 선택이 "뭘 늘리면 좋을까?", "마늘이랑 양파 중 면적당 조수입이 나은 건?" 같은 질문에서 이 데이터를 선택할 수 있다 (가짜 LLM 종단 간 테스트). 위치 없이도 답할 수 있어야 하며 지도 형식을 강요하지 않는다 (`needs`에 지점 분석이 없으면 `report`/`visual`)
- [x] 결과(HTML)에 한계 문구가 자동으로 들어간다: 도 전체 단위, 조수입 기준(비용·순이익 아님), 자료 기준일 2021-08-09와 최신 연산 20-21, 수익을 보장하지 않음. 렌더가 이 문구를 쓰는 방식은 `geo.climate.limitations`와 같은 패턴을 따른다
- [x] 종단 간 자동 테스트(가짜 LLM, `backend/tests/e2e/fakes.py` 패턴 재사용): 위 두 질문 유형, 그리고 제주시 지점 질문에서 이 데이터가 '지점 단위 분석'에는 쓰이지 않고 보조로만 쓰이는지
- [x] `python -m pytest backend/tests -q` 전체 통과

## Comments

## Result

**만든 것**
- 카탈로그 `catalog/jeju_vegetable_cultivation.json`(허브, 공간 `도 전체`, 시간 `연산(작기)`, 15-16~20-21, 컬럼 role_hint `season/crop_group/crop/area/production/revenue/as_of`, 한계 notes). 파일 로더가 utf-8-sig로 읽어 168행, 연산 6, 노지/시설, 소분류 28종을 확인(테스트).
- 모듈 `modules_seed/market/crop_economics.py` (id `market-crop-economics`, verified, 입력 `cultivation{season, crop_group, crop, area, production, revenue}`). 출력 4개: `crop_metrics`(연산·작목별 면적당 조수입 백만원/ha, 수량 톤/ha, 단가 원/kg, `is_aggregate`), `crop_ranking`(최신 연산 노지/시설별 면적당 조수입 순위, 전 연산 대비·최초 연산 대비 면적 증감 %, n_seasons), `crop_area_trend`(series, 연산별 면적과 직전 연산 대비 %), `limitations`. 단위 변환은 상수(`WON_PER_MW`, `KG_PER_TON`)로 명시, 계산은 전체 정밀도 후 출력만 소수 둘째 자리 반올림. 검증: 20-21 월동무 21.05백만원/ha, 71.12톤/ha, 296.0원/kg. '기타(…)' 2종은 `is_aggregate=True`로 표시하고 순위·추세에서 제외.
- 매핑 데이터 `backend/jejuagent/catalog/crop_name_map.json` + `crop_map.crop_for_cultivar()`. 연결한 것은 `월동무`(가격 품종) <-> `월동무`(재배현황) 하나뿐.
- ②: `runner/selection.py`에 `AGGREGATE_UNITS={"시도","도 전체"}`. 지점 분석에서 도 전체 단위 데이터는 시도와 같이 보조(`auxiliary`)로만 쓰이고, 보조뿐이면 `granularity_mismatch`로 제외되어 infeasible. 프롬프트에 위치 없는 작목 비교 질문에는 이 데이터를 고르라는 한 줄 추가. 지도 형식은 강요하지 않는다(지점 분석 `needs`가 없으면 지도 없음).
- ⑤ `render/html.py`: `_crop_limits()`가 모듈 결과가 있을 때 한계 문구(도 전체 단위, 조수입 기준·순이익 아님, 기준일 2021-08-09·최신 연산 20-21, 수익 보장 안 함, 기타 제외)를 자동으로 싣는다(`site` 한계와 같은 방식).
- 기존 테스트 수정(항목이 4->5개로 늘어서): catalog(id 집합·`len`), selection enum 집합, modules 카탈로그 탐색 `== 5`, e2e API `/api/catalog` 개수.
- 새 테스트 `backend/tests/e2e/test_crop_economics.py`(7개): 로더, 모듈 단위·순위·한계, 매핑, 가짜 LLM 종단 간 2문장("뭘 늘리면 좋을까?", "마늘이랑 양파 중 면적당 조수입이 나은 건?" -> 데이터 선택·verified 모듈 재사용·한계 문구 HTML·지도 없음), 제주시 지점 질문(관측소 primary + 재배현황 auxiliary, '지점 단위 분석 불가' 없음), 재배현황 단독 지점 질문은 infeasible.

**테스트:** `.venv\Scripts\python.exe -m pytest backend/tests -q` -> **199 passed** (약 176초). 실제 GPT-4o 호출 없음.

**알려진 한계**
- 가짜 LLM만으로 검증했다. 실제 GPT-4o가 "마늘이랑 양파" 질문에서 작목(구마늘/잎마늘, 양파_조생/양파_만생)을 비교 대상으로 골라 보고서에 싣는지는 미확인(모듈은 전 작목 순위를 모두 낸다).
- 작목 일부(방울다다기 양배추, 비트 등)는 6개 연산 중 3개만 있다. `area_change_pct_vs_first`는 그 작목의 첫 연산 기준이고 `n_seasons`로 표시한다. 직전 연산 대비 증감은 행 순서상 이전 연산이라 연산이 비어 있으면 비연속 비교가 될 수 있다.
- 면적당 조수입은 노지/시설을 따로 순위 매기며(시설은 면적당 값이 훨씬 큼) 둘을 한 순위로 섞지 않는다. 마늘(구마늘·잎마늘)·양파(조생·만생)는 별도 작목이라 "마늘 대 양파"는 보고서에서 사용자가 묶어 읽는다.
- 렌더 `_crop_limits`는 모듈 파일을 importlib로 읽는다(site와 같은 방식, 별도 공유 코드 없음). 제목 일치로 모듈 결과를 판별한다.

**미확인/연결하지 못한 것**
- 허브 가격 품종과 연결하지 못한 것(이름이 달라 확인 불가): 당근(일반)/세척당근/흙당근 <-> 당근, 깐마늘/마늘/햇마늘(남도 등) <-> 구마늘·잎마늘, 세척무 <-> 월동무, 양배추(일반/수입)/저장양배추 <-> 양배추, 양파 계열(저장양파, 중만생양파 등) <-> 양파_조생·양파_만생. `crop_name_map.json`의 `maps`에는 월동무만 있다.
- 작목 간 가격-재배현황 결합 분석(단가 비교 등)은 만들지 않았다.

**13(평가 도구)이 쓸 인터페이스**
- 카탈로그 id `jeju_vegetable_cultivation`, 모듈 id `market-crop-economics`, 입력 역할 `cultivation`: `season`(연산), `crop_group`(채소구분대분류), `crop`(채소구분소분류), `area`(면적(ha)), `production`(생산량(톤)), `revenue`(조수입(백만원)). 출력 id `crop_metrics`, `crop_ranking`, `crop_area_trend`, `limitations`.
- 가짜 LLM 예: `backend/tests/e2e/test_crop_economics.py`의 `_crop_llm(selected)`. 지점 질문에서 이 데이터는 `role == "auxiliary"`이다.
