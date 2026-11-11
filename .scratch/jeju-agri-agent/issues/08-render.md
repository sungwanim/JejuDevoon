# 08: 렌더: HTML 3종 + 숫자 근거 대조

**What to build:** 분석 결과가 요청에 맞는 HTML(보고서형 / 그림·흐름도 중심 / 지도 중심)로 만들어지고 본문의 숫자는 모두 중간산출물에서 온 값이다. 화면에서 결과를 보고 저장할 수 있다. 단계 ⑤ 파일과 렌더 패키지를 소유한다. 읽을 것: `.scratch/jeju-agri-agent/spec.md`의 ⑤ 렌더.

**Blocked by:** 04, 06

**Status:** done

- [x] LLM이 `ReportSpec`(제목, 3문장 이내 요약, 섹션 목록(제목, 설명 문장, 블록 목록), 한계 목록)을 구조화 출력으로 낸다. 블록 종류: 차트·지도·흐름도(Mermaid)·표·강조 상자, 데이터는 중간산출물 id로 참조한다. LLM은 숫자를 직접 쓰지 않는다
- [x] **숫자 근거 대조:** 본문 숫자를 뽑아 중간산출물 값과 대조(반올림 허용)하고 근거 없는 숫자가 든 문장은 바로 제거한다
- [x] 템플릿(독립 HTML 한 파일): `report`(요약 → 방법 → 결과 → 한계 → 출처), `visual`(큰 결론 → 흐름도 → 단순 차트 → 쉬운 설명), `map`(지도 중심 + 요약·차트). 차트·흐름도·지도 라이브러리는 CDN
- [x] 모든 산출물에 공통 섹션이 들어간다: 사용한 데이터 / 제외한 데이터와 이유, 분석 과정(모듈 id·버전), 근거와 한계, 데이터 출처·이용조건, 답하지 못한 부분과 이유
- [x] 공간 정보가 필요한 요청은 스타일과 무관하게 항상 `map`
- [x] 화면에서 결과 HTML을 보고 파일로 저장할 수 있다
- [x] 자동 테스트(Runner 경계): 형식 3종, 근거 없는 숫자 문장 제거, 공통 섹션 포함, `partial`일 때 답하지 못한 부분 표시

## Comments

## Result

**만든 것**
- `backend/jejuagent/render/`: `spec.py`(ReportSpec 스키마·프롬프트·검증·LLM 없는 `fallback_spec`), `numbers.py`(숫자 근거 대조), `html.py` + `report.html.j2`(Jinja2 자동 이스케이프, 독립 HTML 한 파일), `__init__.py`의 `build_html(state, ctx)`.
- `runner/stages/s5_render.py`: 렌더 + 종료 상태 결정. 상한·로드 실패·unanswered·성공 못 한 작업이 있으면 `partial`, 아니면 `answered`. 중간산출물·unanswered·상한·로드실패가 모두 없으면 통과(HTML 없음, 기존 러너 테스트 호환).
- 프런트: `ResultView.tsx`에 "결과를 HTML 파일로 저장" 버튼(Blob 다운로드). iframe `srcdoc` 보기는 기존 그대로. `npm run build` 통과.
- 템플릿 3종(`report`/`visual`/`map`)은 한 파일의 부분 순서만 다르다(report: 요약, 방법, 결과, 답 못한 부분, 한계, 출처 / visual: 큰 결론, 흐름도, 쉬운 설명 / map: 지도 맨 위). 공통 섹션 6종은 모든 형식에 있다. 형식은 `plan.output_format`을 그대로 따른다.
- 차트(Chart.js 4.4.7)·흐름도(Mermaid 10.9.3)·지도(Leaflet 1.9.4)는 CDN 고정 버전. 로드 실패 시 차트는 "표로 보기"(기본 펼침), 지도는 좌표 표, 흐름도는 번호 목록이 남는다. 데이터는 `<script type="application/json">`에 `<`,`>`,`&`를 유니코드 이스케이프해 넣고, Mermaid 라벨은 허용 문자만 남긴다(`securityLevel: strict`).
- 숫자 규칙은 `numbers.py` 상단 독스트링에 문서화: 근거 집합(셀 값, 열 통계, 첫-끝 변화량·변화율, 표 크기, 요청에 있던 숫자, 개수), 반올림 허용, 만/천/억 환산, 면제(연·월·일, 날짜, 서수·'3문장' 등, 목록 번호, 영문 식별자). 걸린 문장은 문장 단위로 제거하고 trace `decision`의 `removed_sentences`에 원문을 남기며, 본문 "근거와 한계"에 제거 개수를 표시.
- 합성 데이터 경고(카탈로그 `synthetic: true`가 사용 데이터에 하나라도 있으면 최상단 붉은 배너), `plan.notice` 표시, 자동 한계 문구(합성 값, 90m DEM·경사·일사 미반영, 한계온도 미판정, 제주시 감귤 데이터 없음, 상한 도달).

**테스트** `backend/tests/render/test_render.py` 16개(형식 3종, 공통 섹션, 근거 없는 숫자 제거, 규칙 단위, partial 미답변 표시, 합성 경고, 이스케이프/JSON 안전, 상한 폴백(LLM 호출 0회), LLM 오류 폴백). render+runner+parse+selection+analysis+catalog+data 63개 통과.

**알려진 한계**
- 실제 브라우저에서 CDN 차트·지도·흐름도 렌더는 확인하지 못했다(미리보기 창이 file:// 페이지를 정적으로만 보여 줌). CDN SRI 해시는 넣지 않았다. 센터 PC에서 한 번 눈으로 확인 필요. 개발 서버도 띄우지 않았다(빌드만 확인).
- 근거 대조는 숫자 값만 본다(단위·대상이 틀려도 우연히 같은 값이면 통과). 근거 집합이 넓어 우연 일치 가능성이 있다.
- 분석 과정 표의 "모듈·버전"은 지금 `module_title`과 `code_hash`다. 07이 task에 `module_id`/`module_version`을 넣으면 자동으로 그 값을 쓴다.
- `map` 블록은 산출물에 `lat`,`lon` 열이 있을 때만 점을 찍고, 아니면 `plan.location` 한 점만 표시한다.

**후속(13) 인터페이스**: `render.build_html(state, ctx) -> (html, {"removed": [...], "fallback": bool, "reason": str})`, `render.numbers.check_sentence/extract_numbers/grounded_numbers`, 합성 경고 문구 상수 `render.SYNTH_WARNING`. 정상 경로 LLM 호출은 `purpose="s5_report_spec"` 1회(스키마명 `report_spec`).
