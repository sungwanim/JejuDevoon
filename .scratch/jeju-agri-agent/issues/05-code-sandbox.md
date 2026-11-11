# 05: 생성 코드 실행기 (보조 경계)

**What to build:** LLM이 만든 분석 코드를 격리된 별도 프로세스에서 안전하게 검증하고 실행한다. 이 티켓은 **보조 테스트 경계**이며 Runner와 독립적으로 테스트된다. 읽을 것: `.scratch/jeju-agri-agent/spec.md`의 '생성 코드 실행기', '코드 계약', '검증 순서'. 01과 병렬로 진행되므로 Runner 코드에 의존하지 않는다 (고정 도구 라이브러리는 03이 만들므로 import 허용 목록의 이름만 정의).

**Blocked by:** None (can start immediately)

**Status:** done

- [x] 입력(코드 문자열, 입력 데이터프레임들, 파라미터)을 받아 출력(중간산출물 사전, 검증 결과, 실패 분류, 실행 시간)을 돌려주는 함수가 있다
- [x] 코드 계약: 메타데이터, 실행 함수, 검증 함수를 갖춘 모듈 형태를 검사한다 (없으면 실패)
- [x] 정적 검사: 문법 오류, import 허용 목록(pandas, numpy, scipy, 표준 math·statistics·datetime·json·re 등, 고정 도구 라이브러리) 위반, 금지 호출(`os.system`, `subprocess`, `socket`, `eval`, `exec`, 작업 폴더 밖 파일 쓰기)을 차단한다
- [x] 별도 프로세스(`python -I`)에서 실행하고 제한시간(기본 60초, 설정 가능) 초과 시 강제 종료하며 '시간 초과'로 분류한다
- [x] 생성 코드 실행 환경에 비밀값 환경변수(`OPENAI_API_KEY` 등)가 없고 네트워크가 막혀 있다 (테스트로 확인)
- [x] 출력이 설계한 중간산출물 스키마(id, 종류, 컬럼·타입)와 다르면 실패한다
- [x] 검증 함수가 문제 목록을 반환하면 실패하고 내용이 전달된다. 공통 검사(빈 결과, 전부 결측)도 적용한다
- [x] mock 생성: Profile(타입, 범위, 결측률, 샘플 값)로 가짜 데이터프레임을 만들어 같은 코드를 실행해 본다
- [x] 실패 분류: 컬럼·역할 불일치, 형식 오류, 금지 사항, 시간 초과, 검증 실패, 데이터 문제(빈 데이터·필요 기간 없음)가 대표 오류에서 올바르게 나온다
- [x] 자동 테스트(`pytest backend/tests/sandbox`)가 키·네트워크 없이 통과한다. 한계(LLM 실수를 막는 장치이지 악의적 코드를 막는 보안 샌드박스가 아님)를 모듈 문서에 적는다

## Comments

## Result

**만든 것** (`backend/jejuagent/sandbox/`): `executor.py`(공개 함수 `run_generated_code`, 스키마·공통 검사, 실패 분류), `static_check.py`(문법·계약·import 허용 목록·금지 호출), `worker.py`(자식 프로세스 진입점, 네트워크·쓰기 차단 훅), `mock.py`(Profile -> 가짜 DataFrame), `README.md`(코드 계약, 실패 분류표, 격리 수준, 한계).

**테스트**: `.venv\Scripts\python.exe -m pytest backend/tests/sandbox` -> 66 passed (약 70초, 키·네트워크 불필요). 금지 import·호출, 시간 초과 강제 종료(자식 PID 사망 확인), 비밀값 환경변수 부재, 네트워크 차단, 작업 폴더 밖 쓰기 차단, 스키마 불일치, check() 문제 전달, 공통 검사, 대표 오류 분류, mock 반영을 증명한다.

**알려진 한계**: LLM 실수를 막는 장치이며 보안 샌드박스가 아니다. 정적 검사는 AST 이름 매칭(별칭·getattr 우회 가능), 네트워크·쓰기 차단은 자식 프로세스 안의 파이썬 훅(`_socket`, `os.open`, ctypes 우회 가능), 읽기·메모리·CPU 제한 없음. data_problem/column_role_mismatch의 예외 기반 분류는 메시지 휴리스틱. Profile 모양은 DESIGN.md §2 ③을 가정(03 확정 후 `mock.py` 확인 필요). `jejukit`는 import 이름만 허용하며 실제 경로는 `extra_sys_paths`로 넘긴다.
