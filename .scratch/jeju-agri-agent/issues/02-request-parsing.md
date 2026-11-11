# 02: 요청 규격화 + 되묻기 + 지도 클릭

**What to build:** 사용자가 지도에서 위치를 클릭하고 질문하면 Agent가 요청을 규격화한다. 필수 정보가 빠지면 질문 1개를 되묻고, 사용자가 답하면 이전 계획과 합쳐 이어서 진행한다. 산출물 형식(report/visual/map)이 규칙으로 정해진다. 단계 ① 파일(`runner/stages/s1_parse.py`)과 지도 컴포넌트를 소유한다. 읽을 것: `.scratch/jeju-agri-agent/spec.md`의 ① 요청 규격화.

**Blocked by:** 01

**Status:** done

- [x] LLM이 `RequestPlan`(목표 한 문장, 하위 질문 목록, 필요한 성격(지점 분석·시계열·공간 비교), 위치, 작목, 기간, 스타일, 빠진 필수 정보, 도메인 여부와 이유, 보조 태그)을 구조화 출력으로 낸다
- [x] 질문 유형(intent) 목록으로 분류하지 않는다. 하위 질문은 LLM이 직접 분해한다
- [x] 코드 규칙: 지점 분석 또는 공간 비교가 필요하면 형식은 항상 `map`, 아니면 스타일에 따라 `report`/`visual`
- [x] 필수 정보가 비어 있으면 `clarify` 상태로 질문 1개를 돌려주고 대화 상태에 `RequestPlan`을 남긴다. 답이 오면 이전 계획과 합쳐 다시 규격화한다 (자동 테스트)
- [x] 도메인 밖이면 `infeasible`. 수익 보장 요청은 불가가 아니라 '수익은 보장할 수 없고 적합도·시세 신호를 보여준다'는 재구성 안내로 이어진다
- [x] 좌표가 제주 본섬 범위(대략적 경계) 밖이면 범위 밖 안내를 낸다 (바다 판정은 10에서 정확해진다)
- [x] react-leaflet 제주 본섬 지도에서 클릭하면 위치 마커가 표시되고 요청에 좌표가 실려 간다
- [x] 되묻기 답변을 이어 쓸 수 있는 채팅 흐름이 화면에 있다
- [x] 자동 테스트(가짜 LLM): 도메인 밖, 위치 없음 되묻기→답변 이어짐, 수익 보장 요청, 형식 결정 규칙 조합

## Comments

## Result

**만든 것**
- `backend/jejuagent/runner/request_plan.py`: `REQUEST_PLAN_SCHEMA`(strict), `normalize`(기본값·좌표 확정: 클릭 > LLM > 이전 계획), `apply_rules`(점 분석인데 좌표 없으면 missing에 "위치", `output_format` 결정), `output_format`, `clarify_question`, **`out_of_range(lat, lon) -> str|None`**(대략 bbox, 티켓 10이 이 함수 하나를 바다 마스크로 교체), `PROFIT_NOTICE`.
- `runner/stages/s1_parse.py`: LLM 1회 호출로 RequestPlan 생성 후 규칙 적용. 도메인 밖/범위 밖 -> `infeasible`, missing -> `clarify`(질문 1개는 `state.reason`), 수익 보장 -> 계속 진행하며 `plan["notice"]`와 `state.extra["notices"]`에 재구성 안내.
- 프런트: `components/JejuMap.tsx`(react-leaflet, OSM 타일+출처 표기, 클릭 마커), `App.tsx`에 지도 연결(클릭 좌표를 `startRun`의 lat/lon으로 전송, clarify 때 안내 문구), `styles.css`. 의존성 `react-leaflet`, `leaflet`, `@types/leaflet`.
- `backend/tests/parse/`: 테스트 + 화면 확인용 `demo_app.py`(테스트 아님, 키워드 가짜 LLM).

**테스트**: `pytest backend/tests/parse backend/tests/runner` -> 20 passed (parse 10). `npm run build` 통과. 브라우저(데모 서버)에서 "감귤 재배 적합도" -> 되묻기 -> 지도 클릭(마커·좌표 표시) -> "여기요" -> answered 확인. 띄운 서버는 포트 PID로 종료함.

**알려진 한계**
- `api/main.py`의 `JEJU_LLM=fake` 데모는 도메인 판정만 흉내내므로(01 소유) 되묻기는 데모하지 못한다. 화면 확인은 `tests/parse/demo_app.py` 사용.
- 범위 판정은 bbox라 바다·우도·마라도 구분 불가. 좌표가 텍스트로만 주어지는 지역(예: "한림읍")은 좌표가 없어 지점 분석이면 지도 클릭을 되묻는다(지오코딩 없음).
- 기존 01 테스트의 응답 형식(`in_domain`, `reason`만)도 기본값으로 처리된다(`normalize`).

**후속 티켓용 인터페이스**
- `state.plan` 필드: goal, sub_questions, needs{point_analysis,time_series,spatial_comparison}, location{kind,text,lat,lon}, crop, period, style(report|easy|unspecified), missing, clarify_question, in_domain, domain_reason, profit_guarantee, tags, output_format(map|report|visual), (notice).
- 되묻기 `prev`는 `{"plan":..., "request":...}`(API가 이미 그렇게 저장).
