# 04: 데이터 선택 + 불가/부분 답변 + 실행 기록 패널

**What to build:** 질문에 맞는 데이터를 Agent가 고르고, 쓰지 않은 데이터와 이유를 화면에서 볼 수 있다. 쓸 데이터가 없으면 `infeasible`로 필요한 데이터를 안내하고, 일부 하위 질문만 답할 수 있으면 `partial`로 표시한다. 단계 ② 파일과 실행 기록 패널을 소유한다. 읽을 것: `.scratch/jeju-agri-agent/spec.md`의 ② 데이터 선택.

**Blocked by:** 02, 03

**Status:** done

- [x] LLM에는 카탈로그 요약(제목, 출처, 공간·시간 단위, 범위, 컬럼 이름·의미·단위)만 주고 데이터셋 id는 스키마 enum으로 제한한다 (없는 id 불가능)
- [x] `Selection`: 실행 가능 여부, 선택 목록(id, 이유, 필요한 컬럼), 제외 목록(id, 이유 코드 `irrelevant/granularity_mismatch/out_of_region/out_of_period/missing_columns`, 메모), 답할 수 없는 하위 질문과 이유, 불가 이유
- [x] 코드 규칙 필터: 지점 분석이 필요한데 지점·격자·관측소 단위 데이터가 하나도 없으면 불가. 시도 단위 데이터는 지점 분석에서 보조로만 쓰인다. 기간이 겹치지 않으면 자동 제외
- [x] 카탈로그가 30개를 넘으면 키워드·임베딩으로 상위 20개만 LLM에 보낸다 (테스트용 큰 카탈로그로 확인)
- [x] 제주시 지점에서 감귤 질문 → 서귀포시 데이터만 있다는 사실이 '답할 수 없는 부분'으로 표시되고 `partial`로 진행한다
- [x] 쓸 데이터가 없는 요청 → `infeasible`과 '어떤 데이터가 있어야 하는지' 안내
- [x] 화면의 실행 기록 패널에 사용한 데이터 / 제외한 데이터와 이유, 하위 질문별 상태가 보인다
- [x] 자동 테스트(가짜 LLM): 데이터 선택·제외, 해상도 불일치 제외, 불가, 부분 답변, 없는 id 차단

## Comments

## Result

**만든 것**
- `runner/selection.py`(스키마·규칙·후보 축소), `runner/stages/s2_select.py`, `backend/tests/selection/test_selection.py`, `frontend/src/components/SelectionPanel.tsx`(+App.tsx 연결 2줄, styles.css 몇 줄).
- LLM 입력은 카탈로그 요약(id·제목·출처·공간/시간 단위·범위·컬럼 이름/의미/단위)뿐, id는 스키마 enum. 규칙이 LLM 결과를 수정: 기간 불일치(`out_of_period`), 시/지역 불일치(`out_of_region`), 없는 컬럼(`missing_columns`), 지점 분석에서 시도 단위(보조 `role=auxiliary`, 주 데이터가 없으면 `granularity_mismatch`로 제외), LLM이 언급 안 한 데이터는 `irrelevant`(by=rule).
- 카탈로그 > 30개면 글자 2-gram 겹침으로 상위 20개만 LLM에 전달.

**테스트**: `pytest backend/tests/selection runner parse catalog data` 39 통과(키·네트워크 없음). `npm run build` 통과. 브라우저 실행 확인은 하지 않음(백엔드+LLM 키 필요).

**인터페이스**
- `state.selection = {feasible, selected:[{dataset_id, reason, columns, role: primary|auxiliary}], excluded:[{dataset_id, reason_code, note, by: llm|rule}], unanswered:[{what, why}], sub_questions:[{question, status: planned|unanswered, why}], infeasible_reason, needed_data}`.
- 제외 이유 코드: `irrelevant, granularity_mismatch, out_of_region, out_of_period, missing_columns`.
- `state.unanswered`는 `[{what, why}]`. s2가 추가만 하고 상태는 안 정함 -> 러너 기본값이 `partial`로 마감(08은 `state.unanswered`를 그대로 렌더하면 됨).
- 선택 결과가 비면 `state.finish("infeasible", reason)` + `state.needed_data`.
- 패널은 trace의 `decision`(stage=s2_select) 이벤트를 읽는다(selected/excluded/sub_questions/unanswered).

**알려진 한계**
- 카탈로그가 비어 있으면(EmptyRegistry) 선택 단계를 통과시킴(기존 runner/parse 테스트 유지 위해).
- 지역 판정은 `location.text`에 "제주시/서귀포시" 글자가 있을 때만(좌표->시 판정 없음). 기간 판정은 4자리 연도 텍스트만.
- 현재 카탈로그에 지점·격자·관측소 데이터가 없어 지점 분석 요청은 항상 "지점 단위 분석" unanswered가 붙는다. 다른 데이터가 하나도 남지 않을 때만 infeasible.
- 제주시 + 감귤만 요청하면 서귀포 데이터가 제외돼 남는 데이터가 없으면 infeasible(허브 가격 데이터 등이 같이 선택될 때 partial).
- 후보 축소는 임베딩이 아님.
