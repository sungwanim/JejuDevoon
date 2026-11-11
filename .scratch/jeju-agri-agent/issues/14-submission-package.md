# 14: 제출 패키지 (README·매뉴얼·데이터 활용 명세)

**What to build:** 센터 운영자가 README만 보고 설치부터 실행까지 할 수 있고, 데이터 출처·이용조건·외부 데이터·오픈소스·사용 AI 모델이 명세로 갖춰진다. 비밀값은 제출물에 없다. 읽을 것: `.scratch/jeju-agri-agent/spec.md`의 Further Notes(제출물 요구사항).

**Blocked by:** 13

**Status:** done

- [x] README: 센터 PC 사양 기준 설치 절차, 의존성 목록, 환경변수 예시(`.env.example`), 실행 방법, 스냅샷 모드와 라이브 모드 설명, 오류와 제약사항
- [x] 사용자 매뉴얼: 지도 클릭, 질문 예시, 결과 보는 법, 한계 해석법 (비전문가 도민 대상)
- [x] 데이터 활용 명세: 필수 데이터(허브 4종) 사용 내역, 출처·이용조건, 전처리와 분석 흐름, 외부 데이터(AWS, DEM, KAMIS 등)·오픈소스 목록
- [x] AI 사용 명세: 사용 모델(GPT-4o), AI 활용 범위, 외부 API·서비스, 생성 코드 실행 격리의 한계
- [x] 결과 설명자료: 문제 정의, Agent 구조, 주요 기능, 실행 결과, 검증 방법·한계, 센터 활용 방안
- [x] 제출용 zip을 만드는 절차(또는 스크립트)가 있고 비밀값·`.env`·개인정보가 포함되지 않았는지 점검하는 단계가 있다
- [x] 깨끗한 환경에서 README대로 따라 해서 대표 질문이 재현되는지 확인한 기록이 있다

## Comments

## Result

**만든 문서:** 루트 `README.md`, `docs/submission/user-manual.md`, `data-spec.md`, `ai-usage.md`, `result-summary.md`, 제출 zip 스크립트 `scripts/make_submission.py`. 이어받아 현재 사실로 갱신: 허브 필수 데이터 4종(채소재배현황 `jeju_vegetable_cultivation`, 모듈 `market-crop-economics`), 지점 기후 합성, 문헌 기준표·적합도 기본 꺼짐(`JEJU_SUITABILITY=1`), 한계온도 판정 안 함, 농업기상 API 명세 3종은 확보했으나 코드 미호출·키 필요·제4유형 문의 예정, 평가 도구 미실행, 실제 GPT-4o 미검증.

**zip 스크립트:** `python scripts/make_submission.py --out <프로젝트 밖 경로>`. 포함 backend/frontend/catalog/snapshots/docs/data/README/DESIGN/.env.example, 제외 .env·.venv·.cache·runs·module_store·node_modules·dist·__pycache__·.git·.scratch. zip을 다시 열어 키 패턴(`sk-…`, 키 대입, serviceKey, 허브 URL 키)을 점검하고 발견 시 zip 삭제 + 종료코드 1. 실행 결과 159개 파일, 2.0MB, 점검 통과. 프로젝트 안에는 zip을 만들지 않는다.

**깨끗한 환경 재현(scratchpad에 zip을 풀어서):** 새 venv(3.14.8) + requirements 설치 성공, `pytest backend/tests/runner backend/tests/catalog backend/tests/e2e` 31개 통과, `jejuagent.api.main` import 성공, `npm ci` + `npm run build` 성공. 전체 199개 재실행과 개발 서버 브라우저 확인은 하지 않았다(e2e 테스트가 대표 질문을 가짜 LLM으로 재현).

**비어 있는 부분:** 평가 수치(티켓 13 미실행, 문서에 "미실행"으로 표기), 실데이터(허브 거래 API 실수집·실호출 미확인, 가격·기온은 합성), 실제 GPT-4o 종단 간 검증, 데이터 이용조건(공공누리 유형 등 다수 "미확인"), 센터 PC 사양 실측.

**점검 경고(소유 밖이라 수정 안 함):** zip 점검 경고로 `backend/jejuagent/modules_seed/market/*.py`의 `verified_by: "sungw (...)"`와 `backend/jejuagent/sandbox/README.md`의 로컬 경로(Windows 사용자명 포함)가 제출물에 들어간다. 제출 전 제거 여부를 사용자가 결정할 것. 테스트의 가짜 이메일·키는 정상.
