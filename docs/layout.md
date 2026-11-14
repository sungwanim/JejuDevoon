# 프로젝트 레이아웃과 병렬 작업 규칙

여러 에이전트가 같은 작업 트리에서 동시에 일한다 (저장소에 커밋이 아직 없어 워크트리 격리를 쓸 수 없다). 충돌을 피하려고 **티켓마다 소유 경로를 정하고, 자기 경로 밖은 읽기만 한다.**

## 디렉터리와 소유

```
backend/
  requirements.txt            # 환경 설정자가 관리. 새 의존성이 필요하면 티켓에 적고 이 파일에 한 줄 추가
  jejuagent/
    runner/                   # 01 소유. 상태 머신, RunState, trace, 파이프라인 등록부
      stages/                 # 단계별 파일. s1_parse.py(02) s2_select.py(04) s3_load.py(03) s4_analyze.py(06) s5_render.py(08)
    llm/                      # 01 소유. 어댑터(OpenAI + 가짜)
    api/                      # 01 소유. FastAPI
    sandbox/                  # 05 소유. 생성 코드 실행기
    catalog/                  # 03 소유. 카탈로그 로더, Profile
    data/                     # 03 소유(로더·변환), 09가 live/ 하위에 추가
    analysis/                 # 06 소유. 작업 목록, 코드 생성, 검증, 재시도
    modules_lib/              # 07 소유. 모듈 저장·검색·재사용
    render/                   # 08 소유. ReportSpec, 숫자 근거, 템플릿
    geo/                      # 10 소유(dem.py), 12가 climate.py 추가
  tests/<영역>/               # 영역 이름은 위 패키지와 같다. 자기 영역만 쓴다
frontend/                     # Vite + React. 01이 뼈대를 만들고, 02/04/08이 각자 컴포넌트를 추가
catalog/                      # 데이터셋 카탈로그 JSON (03)
snapshots/                    # 데이터 스냅샷 (03 샘플, 09 실데이터)
module_store/                 # 저장된 분석 모듈 (07)
runs/                         # 실행 기록 trace (gitignore)
eval/                         # 평가 도구와 시험지 (13)
docs/                         # 설계 문서, 사용자 매뉴얼
data/                         # 원본 입력(DEM, 허브 명세, 감귤 CSV). 읽기 전용, 수정 금지
```

## 규칙

1. **자기 소유 경로만 수정한다.** 다른 티켓의 경로를 바꿔야 하면 하지 말고 티켓 파일의 Comments에 이유를 적고 멈춘다.
2. **공유 파일은 순서대로만 수정한다.** 파이프라인 등록부(`runner/`의 단계 목록)는 01이 만들고, 이후 티켓은 자기 단계 파일만 바꾼다. 등록부 자체를 바꿔야 할 때는 선행 티켓이 끝난 뒤에만 한다.
3. **테스트는 자기 영역 폴더에만 쓴다.** 실행은 `.venv`의 파이썬으로, 자기 영역만 돌린다 (`pytest backend/tests/<영역>`).
4. **비밀값은 코드·테스트·산출물에 넣지 않는다.** `.env`만 읽고, `.env`는 만들지 않는다 (사용자가 직접 넣는다). 테스트는 키 없이 통과해야 한다.
5. **LLM 호출은 어댑터를 통해서만** 한다. 자동 테스트는 가짜 어댑터로 돌려서 네트워크 없이 통과해야 한다.
6. **외부 데이터를 받는 코드는 스냅샷 폴백이 있어야** 한다.
7. **커밋하지 않는다.** 변경은 작업 트리에 남기고 사용자가 커밋한다.
8. 끝나면 티켓 파일의 `Status:`를 `done`으로 바꾸고, `## Result` 아래에 만든 것·테스트 결과·알려진 한계를 적는다.

## 환경

- 파이썬: 루트의 `.venv` (3.14). 설치된 패키지: fastapi, uvicorn, pandas, numpy, scipy, pytest, httpx, openai, rasterio, pyproj, jinja2, python-dotenv, pyarrow.
- Node 24 / npm 11 (프런트엔드).
- 환경변수 이름(예시): `OPENAI_API_KEY`, `JEJU_HUB_PROJECT_KEY`, `DATA_GO_KR_SERVICE_KEY`.
