# 01: Runner 뼈대 + 채팅 UI + 도메인 밖 불가

**What to build:** 사용자가 채팅창에 요청을 입력하면 Agent Runner가 실행되고, 도메인 밖 요청은 `infeasible`로 돌아와 화면에 이유가 보이며 실행 기록(trace)이 남는다. 이 티켓은 **주 테스트 경계(Runner)와 교체 가능한 어댑터(LLM, 데이터 소스 자리)** 를 완성하는 뼈대다. 단계 ①~⑤는 자리만 잡고(그대로 통과시키는 기본 구현), 각 단계 파일은 이후 티켓이 채운다. 읽을 것: `.scratch/jeju-agri-agent/spec.md`, `docs/agent-flow.md`, `docs/layout.md`(소유 경로와 병렬 작업 규칙).

**Blocked by:** None (can start immediately)

**Status:** done

- [x] 요청 문장을 받아 종료 상태(`answered/partial/clarify/infeasible/failed`), HTML(선택), 실행 기록을 돌려주는 단일 진입점이 있고, 프레임워크 없이 상태 머신으로 구현되어 있다
- [x] `RunState`와 전이 기록(trace)이 실행마다 `runs/`에 JSON으로 저장되고, 단계별 입출력·LLM 호출 정보(모델, 프롬프트 해시, 토큰, 시간)가 남는다
- [x] LLM 어댑터는 구조화 응답(스키마)과 자유 텍스트 두 호출을 제공하고, OpenAI 구현(`temperature=0`, seed 고정, Structured Outputs)과 미리 정한 응답을 순서대로 돌려주는 가짜 구현이 있다
- [x] 데이터 소스 레지스트리 인터페이스(카탈로그 id → 데이터)가 있고 스냅샷 구현의 자리가 있다 (내용은 03이 채움)
- [x] 파이프라인 등록부에 5단계 슬롯이 있고, 각 단계는 별도 파일이며 후속 티켓이 자기 파일만 바꿔도 되게 되어 있다
- [x] 도메인 밖 요청(예: '주식 추천해줘')이 `infeasible`과 이유로 끝난다 (가짜 LLM으로 테스트)
- [x] 실행 상한(LLM 호출 25회, 전체 5분)이 걸려 있고, 넘으면 그때까지의 결과로 종료한다 (테스트)
- [x] FastAPI: 실행 시작, 실행 상태·결과 조회, 카탈로그 목록(빈 목록 가능) 엔드포인트가 있다
- [x] Vite + React 채팅 화면: 입력창, 상태 표시, 실행 기록 보기, 결과 영역. `npm run dev`로 백엔드와 연결되어 도메인 밖 요청의 결과가 화면에 나온다
- [x] OpenAI 키·허브 키는 `.env`에서만 읽고 `.env.example`을 만든다 (실제 `.env`는 만들지 않음)
- [x] 자동 테스트가 키 없이 통과한다 (`pytest backend/tests/runner`)

## Comments

## Result

**만든 것**
- `backend/jejuagent/runner/`: `state.py`(RunState), `pipeline.py`(5단계 등록부 `STAGES`), `runner.py`(`run_agent()` 상태 머신, 상한, trace 저장), `context.py`(RunContext, `ctx.llm` 상한·기록 래퍼), `trace.py`, `datasource.py`(DataSourceRegistry/EmptyRegistry/SnapshotRegistry 자리), `stages/s1~s5_*.py`.
- `backend/jejuagent/llm/`: `LLMClient`(structured/text), `OpenAILLM`(gpt-4o, temperature=0, seed 고정, Structured Outputs strict), `FakeLLM`(응답 순서대로, `calls` 기록; 항목은 dict/str/Exception/callable).
- `backend/jejuagent/api/`: `POST /api/runs`, `GET /api/runs/{id}`, `GET /api/runs/{id}/result`, `GET /api/catalog`. 실행은 backend/에서 `uvicorn jejuagent.api.main:app`. `JEJU_LLM=fake`는 키 없이 화면을 확인하는 데모용.
- `frontend/`: Vite + React + TS. 채팅 입력, 단계 진행 표시, 결과 영역(HTML은 iframe srcDoc), 실행 기록 패널. `/api`는 8000으로 프록시.
- `.env.example`, `backend/tests/runner/`.

**테스트**: `.venv/Scripts/python.exe -m pytest backend/tests/runner` -> 10 passed (키·네트워크 없음). 도메인 밖 -> infeasible, LLM/시간 상한(낮춘 Limits로), trace.json 저장과 LLM 호출 정보, 가짜 LLM 호출 기록, OpenAI 요청 직렬화(네트워크 없이), API 왕복.
`npm install`, `npm run build` 통과. 개발 서버(5173) + 백엔드(8000, JEJU_LLM=fake)로 브라우저에서 "주식 추천해줘" -> "불가" 배지, 이유, 실행 기록이 화면에 나오는 것을 확인.

**알려진 한계**
- s1_parse 기본 구현은 도메인 판정 LLM 호출 1회뿐이다(02가 RequestPlan으로 대체). s2~s5는 통과만 하므로 도메인 안 요청은 HTML 없이 `answered`로 끝난다.
- 상한에 걸리면 러너가 `s5_render`로 건너뛰고(ctx.llm은 막힘), 종료 상태가 비어 있으면 `partial`로 한다.
- API 실행 상태와 되묻기 대화 상태(conversation_id -> prev)는 메모리에만 있다(서버 재시작 시 조회 불가, trace.json은 runs/에 남음).
- 새 의존성 없음.

**후속 티켓용 인터페이스**
- 단계 파일 `runner/stages/sN_*.py`는 `run(state: RunState, ctx: RunContext) -> RunState`. state를 갱신해 돌려주고, 종료하려면 `state.finish(status, reason)` (러너가 그 단계 뒤에서 멈춤). 등록부(`runner/pipeline.py`)는 바꿀 필요 없음.
- RunState 필드: request, click, prev, status/reason/message/needed_data/html/unanswered/limit_hit, plan, selection, data, profiles, load_failures, tasks, artifacts, extra(자유).
- LLM: `ctx.llm.structured(system, user, json_schema, schema_name=..., purpose=...).data` / `ctx.llm.text(system, user).text`. 상한·trace 기록 자동. 테스트는 `run_agent(req, llm=FakeLLM([...]), data=registry, runs_dir=tmp_path)`.
- 데이터: `ctx.data.catalog()`, `ctx.data.load(id)`. 03은 `DataSourceRegistry` 구현을 `run_agent(data=...)`와 `create_app(data=...)`(api/main.py는 01 소유)에 연결해야 한다.
- trace: `ctx.trace.add("decision", stage=..., **필드)`. 러너가 stage/transition/llm_call/limit/error를 자동 기록하고 `runs/{run_id}/trace.json`(+`result.html`)에 단계마다 저장.
