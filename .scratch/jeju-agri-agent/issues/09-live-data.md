# 09: 실데이터 연동 + 스냅샷 + 오류 안내

**What to build:** 허브 API 등에서 실제 데이터를 받아 스냅샷으로 고정하고, 운영 중 외부 서비스가 안 될 때는 스냅샷으로 동작하며 원인과 해결 방법을 알려준다. **실제 호출 확인에는 사용자가 API 키를 `.env`에 넣어야 한다.** 키가 없는 동안에도 코드와 자동 테스트(가짜 서버)는 완성할 수 있다. 읽을 것: `data/docs/schemas/`의 API 명세, `.scratch/jeju-agri-agent/spec.md`의 '데이터' 절.

**Blocked by:** 03

**Status:** done

- [x] 허브 API 클라이언트: 시작일·종료일·품종 필수 파라미터, 페이지당 100건 페이지 처리, `hasMore` 처리, 이동평균은 `period`(1·2·7·30·90). 프로젝트키는 `.env`에서만 읽는다
- [ ] (부분: 이어받기·스냅샷 로직은 완료, 일자료 API 명세 미확인)  기상청 AWS 일자료(공공데이터포털)와 지점정보(위경도·고도) 수집기: 제주 관측소 목록을 받아 10년치 일자료를 일괄 수집해 `snapshots/`에 저장한다. 일일 호출 한도(개발계정 10,000건)를 넘지 않도록 이어받기를 지원한다
- [x] KAMIS 가격 API와 표준코드: 코드 체계가 맞는지 확인해 맞으면 카탈로그에 추가하고, 맞지 않으면 사용하지 않는 이유를 문서에 적는다
- [x] 스냅샷 고정: 받은 데이터는 버전 해시와 함께 저장되어 재현에 쓰인다
- [x] 폴백: 라이브 호출이 실패하면 스냅샷으로 동작하고 키 오류·네트워크 오류·한도 초과를 구분해 원인과 해결 방법을 사용자에게 보여준다
- [x] 외부 호출은 모두 어댑터 뒤에 있어 테스트에서 가짜 서버나 파일로 바꿀 수 있다
- [x] 자동 테스트(키·네트워크 없이): 페이지 처리, 키 오류 메시지, 한도 초과 시 이어받기, 폴백 동작
- [ ] (사용자 키가 있을 때) 실제로 소량 호출해 응답 형식이 명세와 맞는지 확인하고 결과를 `## Result`에 적는다. 키가 없으면 '미확인'이라고 적는다

## Comments

## Result

**만든 것** (`backend/jejuagent/data/live/`)
- `hub.py` `HubClient`: 허브 API(일일 거래 / 이동평균). 시작일·종료일·품종 필수, `period`는 1·2·7·30·90만, `limit` 100 상한, `hasMore`로 페이지 이어붙임. 키는 `JEJU_HUB_PROJECT_KEY`(환경변수/`.env`)에서만 읽고 URL 경로에 쓰이므로 예외·로그에 URL을 남기지 않는다.
- `kma.py`: `DataGoClient`(호출 횟수 계수, 자체 한도 10,000), `collect_stations`(AWS 지점 원본 저장), `jeju_stations`(필드명을 인자로 받아 제주 필터), `collect_daily`((지점, 연도) 단위, 상태 파일로 이어받기, 완료되면 스냅샷 고정). 키 `DATA_GO_KR_SERVICE_KEY`.
- `snapshot.py`: `snapshots/live/{이름}.json` 에 `{meta{version_hash, fetched_at, n_rows, synthetic:false}, data}` 저장. 해시는 data 내용 sha256 앞 16자.
- `errors.py` `LiveError`: no_key / bad_key / network / quota 네 가지, 한국어 원인·해결 방법(`as_dict()`), 키 미포함.
- `registry.py` `LiveRegistry(SnapshotRegistry)`: 허브 데이터셋은 라이브 호출(18개 품종 전부), 성공하면 `snapshots/live/`에 고정. 실패하면 스냅샷으로 폴백. `df.attrs["data_mode"]` = `live|snapshot|fallback`, 폴백이면 `df.attrs["fallback_reason"]`, `registry.notices`에 원인 누적, `df.attrs["snapshot_version"]`에 버전 해시. `snapshots/live/`에 실데이터가 있으면 03의 합성 샘플보다 우선.
- `collect.py`: 수집 명령(아래). `runner/datasource.py`에 `make_registry()` 추가(`JEJU_DATA_MODE=live`면 LiveRegistry). `.env.example`에 `JEJU_DATA_MODE=` 한 줄 추가.
- 테스트 `backend/tests/live/` (가짜 서버 MockTransport): 페이지 처리, 필수·period 검증, 키 없음/키 오류/한도/네트워크 메시지, 키가 로그·예외에 안 나옴, 한도 초과 후 이어받기, 폴백, 스냅샷 고정 해시. `pytest backend/tests/live backend/tests/runner backend/tests/catalog backend/tests/data` -> 38 passed.

**KAMIS 표준코드 판단 (카탈로그에 추가하지 않음)**: 표준코드 API(`katCode/goods`)는 상품 대/중/소분류코드(`gds_lclsf_cd/gds_mclsf_cd/gds_sclsf_cd`)이고, 가격 API(`perDay/price`)는 부류/품목/품종코드(`ctgry_cd/item_cd/vrty_cd`)다. 명세에 두 코드 체계가 같다는 설명이나 매핑이 없고, 가격 API는 코드 값 목록도 제공하지 않는다. 확인되지 않았으므로 추가하지 않았다. 또 거래 가격 API 호출 자체가 키 필요라 카탈로그 컬럼(품목·시장 필드)도 확정할 수 없다. 키로 코드 목록을 받아 비교한 뒤 추가할 것.
**기상 데이터도 카탈로그에 추가하지 않음**: 아직 받은 데이터가 없어 스냅샷이 없고 컬럼명을 모른다(추가하면 04가 없는 데이터를 고르게 된다). 첫 수집 후 컬럼을 보고 `catalog/`에 항목을 추가할 것.

**공식 문서로 확인한 것**
- 지점정보(AWS 지점): `https://apis.data.go.kr/1360000/WethrBasicInfoService/getAwsKORNAData`, 요청 `ServiceKey, pageNo, numOfRows, dataType`. 응답 설명에 지점번호, 시작/종료시각, 지점명, 위도, 경도, 노장 해발고도 등이 있음. 출처 https://www.data.go.kr/data/15058846/openapi.do
- `15057084`는 AWS 1분 자료(`Aws1miInfoService`, 최근 2일만)이고 일자료 오퍼레이션이 아니다. `15139439`는 설명 페이지만 읽혀 오퍼레이션을 확인하지 못했다. `15059466`(방재기상연보, `AwsYearlyInfoService`)은 연·월 요약이다.
- 허브: 명세 hwpx와 동일(URL 형식, number/limit, totCnt/hasMore).

**미확인 (키 필요 또는 문서 미확인)**
- AWS 일자료 API의 URL·요청 파라미터·응답 필드명(문서에서 못 찾음 -> `DailySpec`에 기본값 없이 사용자가 채움). 지점정보 응답의 JSON 필드명(문서엔 한글 설명뿐). 일일 한도 10,000건은 티켓 기준 값, 문서 확인 못 함.
- 포털 오류 코드(30·31·22 등)와 XML 오류 응답 판별은 알려진 공통 값을 쓴 것으로 이 서비스 문서로는 미확인. 허브의 인증 실패·한도 초과 응답 형식은 명세에 없어 HTTP 401/403/429로만 구분(실제는 다를 수 있음).
- 실제 호출로 응답 형식이 명세와 맞는지(허브 두 API, 지점정보) 확인하는 항목은 미확인(키 필요)이라 체크하지 않음. `/api/main.py`가 아직 `make_registry()`를 쓰지 않음(01 소유, 수정 안 함).

**사용자가 할 일**
1. `.env.example`을 `.env`로 복사하고 `JEJU_HUB_PROJECT_KEY`(허브 마이페이지 > 프로젝트 관리의 프로젝트키), `DATA_GO_KR_SERVICE_KEY`를 채운다. 라이브로 쓰려면 `JEJU_DATA_MODE=live`.
2. `backend/`에서: `..\.venv\Scripts\python.exe -m jejuagent.data.live.collect hub 20150101 20251231` (허브 거래·이동평균 수집, 실패 시 원인·해결 방법 출력). `... collect stations` 후 `snapshots/live/kma_aws_stations_raw.json`에서 필드명을 확인하고, 일자료 활용가이드를 보고 `spec.json`(url, station_param, start_param, end_param, date_fmt)을 만들어 `... collect aws-daily --spec spec.json --stations id1,id2 --years 2015 2025`. 한도에 닿으면 멈추므로 다음 날 같은 명령을 다시 실행한다.
3. 첫 수집 결과로 응답 형식이 명세와 다르면 이 티켓 Comments에 알려 달라.
