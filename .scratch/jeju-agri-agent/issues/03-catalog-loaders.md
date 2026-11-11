# 03: 카탈로그 + 데이터 로더 + Profile (스냅샷)

**What to build:** 감귤 CSV와 허브 가격 API의 예시 데이터가 카탈로그에 등록되고, 어느 데이터든 인코딩·문자열 숫자·결측 표기가 처리되어 Profile(샘플 값 3~5개 포함)이 만들어진다. 단계 ③ 파일과 카탈로그, 고정 도구 라이브러리를 소유한다. 라이브 API 호출은 09의 일이며 여기서는 **스냅샷**으로 동작한다. 읽을 것: `.scratch/jeju-agri-agent/spec.md`의 ③과 '데이터' 절, `DESIGN.md` §3.

**Blocked by:** 01

**Status:** done

- [x] 카탈로그 항목 형식(id, 제목, 출처, 접근 방식, 이용조건, 공간 단위, 시간 단위, 범위, 컬럼 이름·의미·단위·역할 힌트, 메모)이 정의되고 JSON으로 저장된다
- [x] 카탈로그에 서귀포시 감귤 생산 정보(원본은 `data/` 폴더의 CSV, 면적 ha, 생산량 톤), 허브 품종별 일일 거래 통계, 허브 이동평균이 등록된다. 거래 API 둘은 `data/docs/schemas/` 명세의 예시를 바탕으로 한 스냅샷 샘플(`snapshots/`)을 쓴다. 단위는 원/kg, 톤, 백만원
- [x] 로더가 파일·스냅샷을 불러오고 인코딩(cp949/utf-8)을 자동 판별한다
- [x] 숫자 문자열을 숫자로 변환하고 **이동평균 API의 `0.00` 결측을 결측으로 처리**한다
- [x] Profile 생성: 행 수, 인코딩, 컬럼별 타입·결측률·최솟값·최댓값·고유값 수·샘플 3~5개, 카탈로그의 의미·단위. 데이터 버전 해시 포함
- [x] 고정 도구: 날짜 파싱, 숫자 변환, 지역 필터, 기간 집계, 키 결합(결합률 보고)이 테스트와 함께 제공된다
- [x] 단계 ③이 선택된 id를 불러오고, 로드에 실패한 데이터는 빼고 진행하며 실패를 기록해 `partial` 신호를 남긴다
- [x] 카탈로그 목록 API가 항목 요약(제목, 출처, 공간·시간 단위, 범위)을 돌려준다
- [x] 자동 테스트: 감귤 CSV(cp949, 넓은 형식), 거래 스냅샷(문자열 숫자, 0 결측) 로드와 Profile, 로드 실패 시 나머지로 진행

## Comments

## Result

**만든 것**
- `catalog/*.json` 3개: `seogwipo_citrus_production`(CSV, cp949, 읍면동·년, 제주시 없음 메모), `jdh_agri_daily_trade`, `jdh_agri_trade_moving_avg`(스냅샷, `synthetic: true`, notes에 "합성 샘플, 실데이터 아님").
- `snapshots/jdh_agri_*.json`: `{"meta": {synthetic:true, ...}, "data": [API 응답 모양, 숫자는 문자열]}`. 6개 품종, 2024-01~03 영업일, 이동평균은 7일(첫 행 등 `0.00` 결측 포함). 재생성: `backend/`에서 `python -m jejuagent.catalog.make_snapshots`.
- `backend/jejuagent/catalog/`: `catalog.py`(load_catalog), `loader.py`(read_csv_auto, load_dataset), `profile.py`(profile).
- `backend/jejuagent/data/tools.py`: 고정 도구. `runner/datasource.py`의 `SnapshotRegistry` 구현, `runner/stages/s3_load.py`, `api/main.py`(`data=SnapshotRegistry()` 한 줄 연결).

**테스트**: `.venv/Scripts/python.exe -m pytest backend/tests/catalog backend/tests/data backend/tests/runner` -> 20 passed (키·네트워크 없음).

**알려진 한계**
- 거래 데이터는 합성 샘플(실데이터 아님, 6/18 품종, 2024-01~03). 이동평균 0.00을 NaN으로 바꾸므로 실제 0과 구분 못 함. 이동평균 period는 7만 있음.
- 라이브 API 호출, 페이지 처리, parquet 캐시는 없음(09). `get_elevation`은 10 소유라 제외. `filter_region`은 이름 일치만(bbox 없음).
- 인코딩 판별은 utf-8 시도 후 cp949 폴백. 로드 실패는 `state.load_failures`에만 기록하고 `state.finish`는 호출하지 않음(전부 실패해도 러너/후속이 판단).
- `/api/catalog`는 카탈로그 항목 전체(`file`, `snapshot` 경로 포함)를 돌려줌. 요약만 필요하면 ②가 필드를 고를 것.

**후속 티켓(04, 06, 09)용 인터페이스**
- 카탈로그 JSON: DESIGN §3 필드 + `access`("file"|"snapshot"), `file`(프로젝트 루트 기준) 또는 `snapshot`(snapshots/ 기준), `synthetic`, 컬럼 `{name, meaning, unit, role_hint, parse?}`. `parse`는 `date | numeric | numeric_zero_missing`(로더가 적용). role_hint: date, variety, price, volume, amount, price_ma, volume_ma, amount_ma, year, region, measure_type, value_by_type, as_of.
- 레지스트리: `SnapshotRegistry()`(기본값은 프로젝트 루트의 catalog/, snapshots/). `.catalog()` -> 항목 목록, `.load(id)` -> 정리된 DataFrame(`df.attrs["encoding"]`), 없으면 `DatasetNotFound`. 09는 같은 클래스 또는 `DataSourceRegistry` 서브클래스에 라이브 호출 + 스냅샷 폴백을 넣고, `load_dataset`의 snapshot 분기를 재사용하면 됨.
- Profile(DESIGN과 같은 필드): `{dataset_id, version_hash(16자, 내용 해시), n_rows, encoding, columns:[{name, meaning, unit, role_hint, dtype(int|float|str|date|bool), null_pct(0~100), min, max, n_unique, samples(3~5)}]}`. date의 min/max는 "YYYY-MM-DD". `jejuagent.catalog.profile(df, id, entry)`. `state.profiles[id]`와 `state.data[id]`에 들어감.
- ③ 입력: `state.selection["selected"]`의 `dataset_id`(문자열 목록도 허용).
- 고정 도구 `jejuagent.data`: `parse_dates(s, fmt=None)`, `to_numeric(s, zero_is_missing=False)`, `filter_region(df, col, regions)`, `resample(df, date_col, freq, agg, by=None)`, `join_on(left, right, key, how="left") -> (df, {left_rows, matched_rows, match_rate, unmatched_keys})`. pandas만 사용.
- 감귤 CSV는 넓은 형식 그대로: `구분`(농가수=호, 면적=ha, 생산량=톤)에 따라 감귤 7종 컬럼의 단위가 바뀜. 읍면동 뒤 공백 제거됨.
