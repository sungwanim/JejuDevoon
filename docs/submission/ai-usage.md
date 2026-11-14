# AI 사용 명세

## 1. 사용 AI 모델

| 구분 | 모델 | 근거 |
|---|---|---|
| 런타임 LLM | OpenAI **GPT-4o** (모델 ID 문자열 `gpt-4o`, `backend/jejuagent/llm/openai_client.py`의 `DEFAULT_MODEL`) | 단일 모델. 다른 LLM은 쓰지 않는다 |
| 호출 설정 | `temperature=0`, `seed=20261120`(고정), Structured Outputs(`response_format=json_schema`, `strict: true`) | `OpenAILLM.build_kwargs` |
| 개발 도구 | **Claude Code** (Anthropic) | 이 프로젝트의 코드·테스트·문서 작성에 사용 |
| 테스트용 | `FakeLLM` (`llm/fake.py`) — 미리 정해 둔 응답을 돌려주는 가짜 | 모든 자동 테스트가 이것으로 동작 |

**검증 상태:** 실제 GPT-4o로 종단 간 실행을 해 보지 못했다(API 키 없이 개발). 프롬프트, Structured Outputs 스키마 호환성, 코드 생성 성공률은 모두 가짜 LLM 기준으로만 검증했다. 모델 응답은 temperature 0과 고정 seed로 변동을 줄이지만 OpenAI가 완전한 동일성을 보장하지는 않는다.

## 2. AI 활용 범위

### 런타임(Agent 실행 중) LLM의 역할
LLM이 하는 일은 5단계 흐름의 판단·생성 부분이다. 계산, 데이터 로드, 상태 전이, 상한 관리는 일반 Python 코드가 한다.

| 단계 | LLM 호출 | 역할 |
|---|---|---|
| ① 요청 규격화 | 1회 | 요청을 목표·하위 질문·필요 성격·위치·작목·누락 정보로 구조화(RequestPlan). 도메인 밖 판정. 좌표·범위·되묻기 규칙은 코드가 적용 |
| ② 데이터 선택 | 1회 | 카탈로그 요약(원본 데이터가 아님)에서 쓸 데이터와 제외 이유를 고름. 규칙이 기간·지역·컬럼·공간 단위 불일치를 교정 |
| ④ 분석 | 작업 계획 1회 + 작업당 코드 생성·수정(최대 2회) + (모듈 후보가 있으면) 재사용/수정/신규 결정 | 분석 작업 목록 설계, pandas 분석 코드 생성, 실패 원인별 최소 수정, 컬럼 역할 매핑 재요청 |
| ⑤ 렌더 | 1회 | 계산된 산출물을 id로 참조하는 보고서 구성(ReportSpec) 설계. 숫자는 쓰지 않게 지시, 쓰면 숫자 근거 대조가 문장을 삭제 |

- 한 실행의 LLM 호출 상한은 25회, 시간 상한 5분(`runner/context.py`의 `Limits`). 재계획은 없다.
- LLM에는 개인정보·키를 보내지 않는다. 보내는 것은 사용자의 질문 문장, 카탈로그·Profile 요약(컬럼 이름·의미·단위·통계·샘플 값), 계산 결과 요약이다. 질문 문장은 사용자가 쓴 그대로 OpenAI로 전송된다.
- LLM이 만든 숫자 문장은 계산 결과에 근거가 없으면 삭제된다(`render/numbers.py`). 이는 단순 값 일치 검사라 단위·대상이 틀려도 우연히 값이 같으면 통과할 수 있다.
- 생성 코드 검증은 mock 데이터 실행으로 오류·형식은 잡지만 계산의 정확성은 잡지 못한다. 정확성 확인(`check()`)도 LLM이 쓴 코드이다.
- 검토된(verified) 시드 모듈(`modules_seed/market`, `modules_seed/site`)이 후보로 잡히면 LLM 코드 생성 없이 재사용한다.

### 개발에 쓴 AI 도구
- 이 프로젝트의 설계 문서, 백엔드·프런트엔드 코드, 자동 테스트, 제출 문서는 **Claude Code**의 지원으로 작성했다. 사람(개발자)이 요구사항·데이터 원칙·범위를 정하고 결과를 검토·실행했다.
- 문헌에서 옮긴 값은 코드와 결과에 쓰지 않는다(`data-spec.md`).

## 3. 외부 API·서비스

| 서비스 | 용도 | 언제 호출 | 키 |
|---|---|---|---|
| OpenAI API (GPT-4o) | 런타임 LLM | 분석 요청 때마다 | `OPENAI_API_KEY` |
| 제주데이터허브 API (`open.jejudatahub.net`) | 농산물 거래 통계·이동평균 수집 | `JEJU_DATA_MODE=live`일 때와 수집 명령. 실호출은 확인하지 못함 | `JEJU_HUB_PROJECT_KEY` |
| 공공데이터포털 (`apis.data.go.kr`) | 기상청 AWS 지점정보 수집 코드가 있음 | 수집 명령을 직접 실행할 때만. 현재 분석 흐름에서는 호출하지 않으며 실호출 미확인 | `DATA_GO_KR_SERVICE_KEY` |
| 농업기상 API (농촌진흥청, 공공데이터포털) | 관측지점 상세정보·상세 관측데이터·생장도일 | **호출하지 않음.** 명세서만 확보했고 코드에 연결하지 않음 | 필요(미보유) |
| OpenStreetMap 타일 (`tile.openstreetmap.org`) | 앱 지도와 지점 결과 지도 배경 | 화면 사용 시 브라우저가 호출 | 없음 |
| CDN: cdn.jsdelivr.net (Chart.js 4.4.7, Mermaid 10.9.3), unpkg.com (Leaflet 1.9.4) | 결과 HTML의 차트·흐름도·지도 | 결과를 열 때 브라우저가 호출 | 없음 |

CDN 3종 중 jsdelivr(2개 라이브러리)와 unpkg가 쓰이며, 차단되면 표·좌표 표·번호 목록으로 대체된다. 허브와 공공데이터포털 키는 URL 경로 또는 쿼리에 쓰이므로 코드가 예외·로그에 URL을 남기지 않게 처리했다.

## 4. 생성 코드 실행 격리의 한계

LLM이 만든 분석 코드는 `backend/jejuagent/sandbox/`의 실행기로 돌린다. 이것은 **LLM의 실수를 막는 장치이며 보안 샌드박스가 아니다.**

하는 일:
- 정적 검사(문법·계약·허용 import 목록·금지 호출)
- 별도 자식 프로세스에서 실행, 시간 제한(작업 실행 1회당 60초, 시간 초과 시 프로세스 트리 강제 종료)
- 환경변수를 허용 목록 방식으로 제거해 API 키를 자식 프로세스에 넘기지 않음
- 자식 프로세스 안의 파이썬 훅으로 네트워크 접속·작업 폴더 밖 쓰기 차단
- 출력 스키마·`check()`·공통 검사(전부 결측, 상식 범위)

하지 못하는 일:
- 정적 검사는 AST 이름 매칭이라 `getattr` 등 별칭으로 우회할 수 있다.
- 네트워크·쓰기 차단은 파이썬 훅이라 `_socket`·`os.open`·ctypes로 우회할 수 있다.
- 파일 읽기, 메모리·CPU 사용은 제한하지 않는다(시간 제한만).
- 따라서 **신뢰할 수 없는 사용자나 외부에 노출된 서비스에서는 쓰지 말 것.** 이 앱은 센터 PC에서 단일 사용자가 로컬로 쓰는 것을 가정한다.

## 5. Prompt 위치

| 파일 | 내용 |
|---|---|
| `backend/jejuagent/runner/stages/s1_parse.py` (`SYSTEM`) | ① 요청 규격화 |
| `backend/jejuagent/runner/request_plan.py` | ① 출력 스키마(`REQUEST_PLAN_SCHEMA`), 규칙, 되묻기·수익 보장 안내 문구 |
| `backend/jejuagent/runner/stages/s2_select.py` (`SYSTEM`) + `runner/selection.py` | ② 데이터 선택 프롬프트·스키마·규칙 |
| `backend/jejuagent/analysis/prompts.py` | ④ 작업 계획(`PLAN_SYSTEM`), 코드 생성(`CODE_SYSTEM`, 코드 계약), 수정(`FIX_SYSTEM`), 역할 매핑 재요청(`REMAP_SYSTEM`), 모듈 재사용 결정(`DECIDE_SYSTEM`), 모듈 수정(`REVISE_SYSTEM`) |
| `backend/jejuagent/render/spec.py` (`SYSTEM`) | ⑤ 보고서 설계 |
| `backend/jejuagent/llm/openai_client.py` | 호출 방식(모델, temperature, seed, Structured Outputs) |

도구·데이터 처리 코드: `backend/jejuagent/data/tools.py`(고정 도구: 날짜 변환·숫자 변환·지역 필터·리샘플·조인), `catalog/loader.py`, `data/live/`(수집), `geo/`(DEM·지점 기후), `modules_seed/`(검토된 모듈), `sandbox/`(실행기).
