# 제주 농업 데이터 분석 Agent

제주 농업 데이터(제주데이터허브 + 공공데이터포털)를 Agent가 탐색·선택·분석해서 HTML 결과(보고서·그림·지도)로 보여주는 로컬 웹앱입니다. 백엔드는 FastAPI, 프런트엔드는 Vite + React, LLM은 OpenAI GPT-4o이며 Agent 흐름은 프레임워크 없이 Python 상태 머신으로 구현했습니다.

> **먼저 읽어 주세요 (현재 상태의 한계)**
> - 가격·거래·기온 데이터는 현재 **합성 샘플**입니다(실데이터 수집은 사용자 API 키가 필요하고 실호출은 확인하지 못했습니다). 합성 데이터를 쓴 결과에는 빨간 경고 배너가 자동으로 붙습니다.
> - 실제 GPT-4o로는 종단 간 검증을 하지 못했습니다. 자동 테스트는 모두 가짜 LLM으로 돌립니다.
> - 허브 필수 데이터는 4종(거래 통계·이동평균 API, 서귀포시 감귤 CSV, 제주채소류재배현황 CSV)이며, 이 중 실데이터로 쓰는 것은 CSV 2종입니다. 지점 기후(`synthetic_aws_daily`)도 합성입니다. 농업기상 API 명세는 확보했지만 코드에서 호출하지 않습니다.
> - 평가 도구(티켓 13)는 아직 실행하지 않아 성능 수치는 없습니다.
> - 수익을 보장하지 않습니다. 재배 적합도와 한계온도(동해 등)는 판정하지 않습니다.

제출 문서는 `docs/submission/`에 있습니다: `user-manual.md`(사용자 매뉴얼), `data-spec.md`(데이터 활용 명세), `ai-usage.md`(AI 사용 명세), `result-summary.md`(결과 설명자료).

## 1. 권장 실행 환경

센터 Agent 운영 PC 최소사양(Intel Core i7-8700 / GTX 1060 / RAM 32GB)에서 돌리는 것을 기준으로 적었습니다. 이 앱은 GPU를 쓰지 않습니다(LLM은 OpenAI 서버에서 실행). 실제 이 사양의 PC에서 실행해 본 것은 아니며(미확인), 개발 PC(Windows 11)에서만 확인했습니다.

| 항목 | 요구 |
|---|---|
| OS | Windows 10/11 (개발·확인은 Windows 11). 다른 OS는 확인하지 않았습니다 |
| Python | 3.14 (개발 환경 3.14.8) |
| Node.js | 24 (개발 환경 v24.21.0, npm 11.19.0) |
| 네트워크 | OpenAI API 호출과, 결과 화면의 지도 타일·차트 라이브러리(CDN) 로딩에 인터넷이 필요합니다 |
| 키 | `OPENAI_API_KEY` 필수(실제 분석). 허브·공공데이터포털 키는 실데이터 수집 때만 |

## 2. 설치

저장소(또는 제출 zip을 푼 폴더) 루트에서 실행합니다. 아래는 PowerShell 기준입니다.

```powershell
# 1) 파이썬 가상환경과 의존성 (backend/requirements.txt)
py -3.14 -m venv .venv
.venv\Scripts\python.exe -m pip install -r backend\requirements.txt

# 2) 프런트엔드 의존성 (frontend/package-lock.json 기준)
cd frontend
npm ci
cd ..

# 3) 환경변수 파일 (키는 직접 입력. 채팅·문서에 붙여넣지 마세요)
copy .env.example .env
notepad .env
```

### 의존성 목록

파이썬 (`backend/requirements.txt`, 버전 고정):
`fastapi==0.162.2`, `httpx==0.28.1`, `Jinja2==3.1.6`, `numpy==2.5.4`, `openai==3.46.0`, `pandas==3.1.1`, `pyarrow==26.0.1`, `pyproj==3.8.0`, `pytest==9.2.0`, `python-dotenv==1.2.4`, `rasterio==1.5.2`, `scipy==1.18.1`, `uvicorn==0.54.0`

프런트엔드 (`frontend/package.json`):
- dependencies: `leaflet ^1.9.4`, `react ^19.3.1`, `react-dom ^19.3.1`, `react-leaflet ^5.0.0`
- devDependencies: `@types/leaflet ^1.9.22`, `@types/react ^19.3.0`, `@types/react-dom ^19.3.0`, `@vitejs/plugin-react ^6.2.1`, `typescript ^7.0.2`, `vite ^8.3.6`

결과 HTML이 CDN에서 불러오는 라이브러리(Chart.js 4.4.7, Mermaid 10.9.3, Leaflet 1.9.4)는 `docs/submission/data-spec.md`의 오픈소스 목록을 보세요.

## 3. 환경변수

`.env`는 프로젝트 루트에 둡니다(`api/main.py`가 루트의 `.env`를 읽음). `.env`는 git과 제출 zip에서 제외됩니다. 키 값은 코드·문서·채팅에 남기지 마세요.

| 변수 | 필수 | 용도 | 비고 |
|---|---|---|---|
| `OPENAI_API_KEY` | 실제 분석에 필수 | OpenAI GPT-4o 호출 | 없으면 요청 시 "OPENAI_API_KEY가 없습니다" 오류 |
| `JEJU_HUB_PROJECT_KEY` | 실데이터 수집 때 | 제주데이터허브 API 프로젝트 키 | 키가 호출 URL 경로에 쓰이므로 예외·로그에 URL을 남기지 않게 처리됨 |
| `DATA_GO_KR_SERVICE_KEY` | 선택 | 공공데이터포털 API 서비스 키 | 현재 기능에서 필수 아님. 지점정보 수집 코드가 읽음 |
| `JEJU_DATA_MODE` | 선택 | `live`이면 허브 API 호출 + 실패 시 스냅샷 폴백. 비우면 스냅샷만 | `.env.example`에 있음 |
| `JEJU_LLM` | 선택 | `fake`이면 키 없이 화면만 확인하는 데모(도메인 판정만 키워드로 흉내) | 실제 분석 불가. 화면 확인용 |
| `JEJU_MODULE_STORE` | 선택 | 분석 모듈 저장소 폴더. `1`/`on`/`true`는 기본 `module_store/` | `api/main.py`는 `ModuleStore()`를 직접 연결하므로 웹앱 실행에서는 이 변수 없이도 `module_store/`를 씀 |
| `JEJU_SUITABILITY` | 선택 | `1`이면 문헌 기반 재배 적합도 표를 켬 | **기본 꺼짐.** 데이터 원칙(공공데이터포털 + 허브만)에 맞지 않아 제출 구성에서는 켜지 않음 |

`.env.example`에는 앞의 네 변수(`OPENAI_API_KEY`, `JEJU_HUB_PROJECT_KEY`, `DATA_GO_KR_SERVICE_KEY`, `JEJU_DATA_MODE`)만 있습니다. 나머지 세 개는 코드가 읽지만 예시 파일에는 없습니다(필요할 때만 `.env`에 줄을 추가하거나 셸 환경변수로 지정).

## 4. 실행

터미널 두 개를 엽니다.

**백엔드 (포트 8000)** — `backend/` 폴더에서:

```powershell
cd backend
..\.venv\Scripts\python.exe -m uvicorn jejuagent.api.main:app --port 8000
```

**프런트엔드 (포트 5173)** — `frontend/` 폴더에서:

```powershell
cd frontend
npm run dev
```

브라우저에서 `http://localhost:5173`을 엽니다. 개발 서버가 `/api`를 `127.0.0.1:8000`(백엔드)으로 넘깁니다(`frontend/vite.config.ts`).

프런트엔드 빌드(타입 검사 + 번들): `cd frontend; npm run build` → `frontend/dist/`. 빌드 결과를 서빙하는 설정(백엔드의 정적 서빙 등)은 없습니다. 실행은 위의 개발 서버 방식입니다.

키 없이 화면만 보려면 백엔드를 `JEJU_LLM=fake`로 띄웁니다(PowerShell: `$env:JEJU_LLM="fake"` 후 같은 uvicorn 명령). 이때는 도메인 밖 요청("주식 추천해줘")을 거절하는 동작 정도만 확인됩니다.

### 스냅샷 모드와 라이브 모드

| 모드 | 설정 | 동작 |
|---|---|---|
| 스냅샷(기본) | `JEJU_DATA_MODE` 비움 | `catalog/`의 카탈로그와 `snapshots/`·`data/`의 파일만 읽음. 네트워크 데이터 호출 없음 |
| 라이브 | `JEJU_DATA_MODE=live` + `JEJU_HUB_PROJECT_KEY` | 허브 가격 데이터는 API를 호출하고 성공하면 `snapshots/live/`에 고정. 실패하면(키 없음·키 오류·한도·네트워크) 원인과 해결 방법을 안내하고 스냅샷으로 폴백. `snapshots/live/`에 실데이터가 있으면 합성 샘플보다 우선 |

**라이브 호출은 키가 없어 실제로 확인하지 못했습니다**(허브 응답 형식·오류 응답은 명세 문서 기준으로 구현, 실호출 미확인).

실데이터 수집(허브 거래·이동평균, 키 필요) — `backend/` 폴더에서:

```powershell
..\.venv\Scripts\python.exe -m jejuagent.data.live.collect hub 20150101 20251231
```

합성 샘플 재생성(키 불필요): `..\.venv\Scripts\python.exe -m jejuagent.catalog.make_snapshots`

## 5. 테스트

프로젝트 루트에서(키·네트워크 불필요, LLM은 가짜):

```powershell
.venv\Scripts\python.exe -m pytest backend/tests -q
```

격리 실행기(sandbox) 테스트가 길어(약 70~80초) 전체는 3분 안팎입니다. 영역별로는 `backend/tests/<영역>`(`runner`, `catalog`, `parse`, `selection`, `data`, `sandbox`, `analysis`, `modules`, `render`, `geo`, `criteria`, `climate`, `live`, `e2e`)을 지정해 돌립니다. 마지막으로 기록된 전체 실행(티켓 17): 199개 통과. 제출 전에 전체를 한 번 다시 돌리세요.

프런트엔드는 별도 테스트가 없고 `npm run build`(타입 검사 포함)만 확인합니다.

## 6. 폴더 구조

```
backend/
  requirements.txt
  jejuagent/
    runner/       상태 머신(run_agent), 5단계(stages/s1~s5), RunState, trace, 데이터 레지스트리
    llm/          LLM 어댑터(OpenAI GPT-4o, 테스트용 가짜)
    api/          FastAPI (main.py가 uvicorn 진입점)
    sandbox/      생성 코드 실행기 (보안 샌드박스 아님, docs/submission/ai-usage.md 참고)
    catalog/      카탈로그 로더, Profile
    data/         고정 도구, live/ (허브·공공데이터포털 수집, 스냅샷 폴백)
    analysis/     작업 계획, 코드 생성 프롬프트(prompts.py), 검증·재시도
    modules_lib/  분석 모듈 저장·검색·재사용
    modules_seed/ 사람이 검토한 verified 모듈 소스
    render/       보고서 스펙, 숫자 근거 대조, HTML 템플릿
    geo/          DEM 고도, 지점 기후 추정
    criteria/     문헌 기반 재배 기준표(기본 꺼짐)
  tests/<영역>/
frontend/         Vite + React (지도, 채팅 입력, 진행 표시, 결과 iframe, 실행 기록)
catalog/          데이터셋 카탈로그 JSON
snapshots/        데이터 스냅샷(합성 샘플 등), snapshots/live/ 는 실데이터 수집 시 생성
data/             원본 입력(국토지리정보원 DEM, 허브 CSV, API 명세서). 읽기 전용
docs/             설계 문서(agent-flow, dem, climate 등)와 submission/(제출 문서)
scripts/          make_submission.py (제출 zip 생성·비밀값 점검)
.env.example      환경변수 예시
(실행 중 생성) runs/ 실행 기록, .cache/dem/ DEM 캐시, module_store/ 저장된 모듈
```

## 7. 오류와 제약사항

- **합성 데이터:** 허브 가격 데이터(6품종, 2024-01~03 영업일), 관측소 기온(합성 12개 관측소)은 합성입니다. 실데이터가 연결되기 전의 결과 수치는 실제와 다릅니다.
- **OPENAI_API_KEY 없음:** 분석 요청이 "OPENAI_API_KEY가 없습니다" 오류로 실패합니다. `.env`를 확인하세요.
- **라이브 모드 폴백 안내:** 키 없음·키 오류·한도 초과·네트워크 오류가 나면 결과에 원인과 해결 방법이 표시되고 스냅샷으로 동작합니다.
- **실행 상한:** 한 번 실행에 LLM 호출 25회, 5분. 걸리면 그때까지의 결과로 만들고 `partial`로 표시합니다. 코드 생성 작업은 작업당 최대 2회 시도(생성 + 수정 1회)이며 재계획은 없습니다.
- **인터넷 필요:** 결과 HTML의 차트·흐름도·지도는 CDN(jsdelivr, unpkg)과 OpenStreetMap 타일을 불러옵니다. 차단되면 차트는 "표로 보기", 지도는 좌표 표, 흐름도는 번호 목록으로 대체됩니다. 실제 브라우저에서 차트·흐름도의 CDN 렌더링을 눈으로 확인하지는 못했습니다.
- **채소재배현황:** 도 전체 단위, 조수입 기준(순이익 아님), 연산 15-16~20-21(기준일 2021-08-09)입니다. 허브 가격 품종과의 이름 연결은 월동무뿐입니다.
- **범위:** 제주 본섬(우도·가파도 포함 격자). 추자도·마라도는 범위 밖입니다. 지점은 지도 클릭으로만 지정합니다(주소·지명 검색 없음).
- **DEM:** 90m 격자 고도 조회뿐이며 경사·사면·일사는 반영하지 않습니다. 바다 마스크는 추정입니다(`docs/dem.md`).
- **판정하지 않는 것:** 한계온도로 재배 가능 여부, 재배 적합도(기본 꺼짐), 수익. 감귤 생산 데이터는 서귀포시뿐입니다.
- **서버 재시작:** 진행 중 실행 상태와 되묻기 대화 상태는 메모리에만 있습니다(`runs/`에는 trace가 남음).
- **보안:** 단일 사용자 로컬 사용을 가정합니다. 생성 코드 실행기는 보안 샌드박스가 아닙니다. 외부에 노출하지 마세요.
- **저작권·귀속:** 결과물은 제주빅데이터센터에 귀속됩니다(대회 규정).
