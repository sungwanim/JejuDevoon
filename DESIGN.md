# 제주 농업 데이터 분석 Agent — 내부 워크플로우 설계 (v0.1 초안)

> 상태: 논의용 초안. 허브 데이터 스키마는 미정.
> 범위: **제주도 본섬 전체** (추자도 등 부속 섬 제외 — DEM 범위 밖).
> DEM: 국토지리정보원 90m로 확정. 용도는 **지점 고도 조회(기온 고도 보정)만**. 경사·사면·일사 모델링은 하지 않고 한계에 "미반영"으로 적는다.
> 확정된 결정: LLM = OpenAI GPT-4o / 인터넷 사용 가능 / 최종 산출물 = HTML / LLM에게 Profile + 컬럼당 샘플 값 3~5개 제공 / 제주데이터허브 데이터 1종 이상 + 외부 데이터 허용 / UI = FastAPI + Vite + React / 생성 모듈은 검증 통과 시 자동 저장(`auto`) / 위치 입력 = 지도 클릭(react-leaflet).

---

## 0. 원칙

1. **LLM은 선택하고 설계하고 설명한다. 숫자는 코드가 만든다.**
2. **LLM은 원본 행 데이터를 통째로 보지 않는다.** 스키마, 요약 Profile, 컬럼당 샘플 값 3~5개만 본다.
3. **모든 단계의 출력은 타입이 고정된 JSON이다** (OpenAI Structured Outputs). 자유 텍스트는 최종 설명 문장뿐이다.
4. **검증을 통과한 분석 코드만 저장하고 재사용한다.** 재사용할 때도 검증은 다시 돌린다.
5. **할 수 없으면 할 수 없다고 말한다.** 이유와 대안을 같이 낸다.
6. **질문 종류(intent)로 경로를 고정하지 않는다.** 할 수 있는 범위는 질문 유형 목록이 아니라 **보유한 데이터(카탈로그)와 도구**가 정한다. Agent는 목표를 직접 분해하고 계획한다. 도메인 경계는 "제주 농업·기후·시장 데이터 분석" 하나뿐이다.

---

## 1. 전체 흐름

> 상세 상태 전이도와 루프 상한: [docs/agent-flow.md](docs/agent-flow.md). 프레임워크(LangGraph 등) 없이 Python 상태 머신으로 구현한다.

```
사용자 자연어
  │
  ▼
① parse_request ──(필수 정보 부족)──► 되묻기 1회
  │ RequestPlan        ──(지원 범위 밖)──► 불가 응답
  ▼
② select_data ──(쓸 데이터 없음)──► 불가 응답 (이유 + 필요한 데이터)
  │ Selection (사용/제외 + 이유)
  ▼
③ load + profile  (고정 도구, LLM 없음)
  │ DataFrame들 + Profile들
  ▼
④ analyze
  │  a. 모듈 라이브러리 검색 → 재사용 / 수정 / 신규 결정
  │  b. 중간산출물 설계 (무엇을 만들지)
  │  c. 코드 생성 (신규·수정일 때)
  │  d. 정적 검사 → mock test → 실데이터 실행 → check()
  │  e. 실패 시 오류를 넣어 재생성 (총 3회까지) → 그래도 실패면 실패 보고
  │ Artifacts (중간산출물)
  ▼
⑤ save_module  (검증 통과한 코드만, status=auto)
  ▼
⑥ render
  │  a. LLM이 ReportSpec(구성안 + 설명) 생성
  │  b. 숫자 근거 대조 (본문 숫자가 Artifact에 있는가)
  │  c. 형식별 템플릿으로 HTML 생성 (report / visual / map)
  ▼
HTML 산출물 + 실행 기록(trace.json)
```

---

## 2. 단계별 명세

### ① parse_request — 요청 규격화

- 입력: 사용자 문장, (있으면) 지도에서 찍은 좌표
- 판단: LLM (Structured Outputs)
- 출력 `RequestPlan`:

```json
{
  "goal": "정규화된 목표 한 문장",
  "sub_questions": ["이 지점의 겨울 최저기온은?", "월동무 최근 3년 가격 추세는?"],
  "needs": {"point_analysis": true, "time_series": true, "spatial_comparison": false},
  "location": {"type": "point | address | region | none", "lat": null, "lon": null, "text": null},
  "crops": ["월동무"],
  "period": {"from": null, "to": null},
  "audience_style": "report | easy",
  "missing": ["location"],
  "in_domain": true,
  "out_of_domain_reason": null,
  "tags": ["price", "climate"]
}
```

- `sub_questions`: 목표를 LLM이 직접 분해한 하위 질문. 정해진 목록에서 고르지 않는다. ④의 작업 그래프의 출발점이 된다.
- `tags`: 경로를 정하는 데 쓰지 않는다. 모듈 검색과 시험지 분류용 보조 정보다.
- 코드 규칙 (LLM 출력 뒤에 적용):
  - `output_format` 결정: 공간 정보가 필요하면(`needs.point_analysis` 또는 `needs.spatial_comparison`) **무조건 `map`**. 아니면 `audience_style`이 `report`면 `report`, `easy`면 `visual`.
  - `missing`이 비어 있지 않으면 되묻기 (예: 지점 분석이 필요한데 위치 없음). LLM이 목표를 보고 무엇이 빠졌는지 직접 판단한다.
  - `in_domain=false`(제주 농업·기후·시장과 무관) → 불가.
  - 제주시 범위 밖 좌표 → 불가.
  - "수익 보장", "얼마 벌 수 있나" 같은 요청 → 불가가 아니라 **재구성 안내** ("수익은 보장할 수 없고, 적합도와 시세 신호를 보여드릴 수 있습니다").

### ② select_data — 데이터 선택

- 입력: `RequestPlan`, 카탈로그 요약 (아래 §3)
- 판단: LLM이 고르고, 코드 규칙이 검증
- 출력 `Selection`:

```json
{
  "feasible": true,
  "selected": [
    {"dataset_id": "jdh_agri_daily_trade", "reason": "...", "columns_needed": ["거래일자", "품종", "평균가"]}
  ],
  "rejected": [
    {"dataset_id": "jdh_flower_by_sido", "reason_code": "granularity_mismatch", "note": "시도 단위라 지점 분석 불가"}
  ],
  "infeasible_reason": null
}
```

- `reason_code`: `irrelevant | granularity_mismatch | out_of_region | out_of_period | missing_columns`
- 코드 규칙:
  - `needs.point_analysis`인데 선택된 데이터의 공간 단위가 `시도`·`none`뿐이면 → 해당 데이터는 보조로만, 지점 데이터가 하나도 없으면 `feasible=false`.
  - 하위 질문 중 일부만 답할 수 있으면 `feasible=true`로 진행하고, 답할 수 없는 하위 질문과 이유를 `infeasible_parts`에 남겨 최종 산출물에 표시한다.
  - 기간이 겹치지 않는 데이터는 자동 제외.
  - LLM이 카탈로그에 없는 id를 내면 Structured Outputs의 enum으로 원천 차단.
- 카탈로그가 30개를 넘으면 키워드 + 임베딩으로 상위 20개만 LLM에 보낸다.

### ③ load + profile — 고정 도구

LLM이 생성하지 않는, 사람이 작성하고 테스트한 함수들. ④의 생성 코드에서도 import해서 쓴다 (`jejukit` 패키지).

| 도구 | 하는 일 |
|---|---|
| `load_dataset(id, filters)` | 파일·API 구분, 인코딩 자동 판별(cp949/utf-8), API 페이지 처리, `data/cache/`에 parquet 캐시 |
| `profile(df)` | 행 수, 컬럼별 타입·결측률·최소·최대·고유값 수·샘플 3~5개 |
| `parse_dates`, `to_numeric(unit)` | 형식 정리 |
| `filter_region(df, bbox \| 행정구역)` | 지역 필터 |
| `resample(df, freq)` | 기간 집계 |
| `join_on(df1, df2, key)` | 결합 + 결합률 보고 |
| `get_elevation(lat, lon)` | 90m DEM에서 지점 고도 조회 (기온 고도 보정용) |

`Profile` 형식:

```json
{
  "dataset_id": "...", "version_hash": "...", "n_rows": 12034, "encoding": "cp949",
  "columns": [
    {"name": "평균가", "meaning": "kg당 평균 거래가", "unit": "원/kg", "dtype": "float",
     "null_pct": 0.8, "min": 120, "max": 9800, "n_unique": 3011, "samples": [1520, 980, 2210]}
  ]
}
```

### ④ analyze — 중간산출물 코드 생성과 검증

**a. 작업 목록.** `sub_questions`와 선택된 데이터로 LLM이 **순서 있는 작업 목록**을 만든다. 각 작업은 "어떤 중간산출물을 어떤 데이터(또는 앞 작업의 중간산출물)로 만드는가"이다. 작업이 끝내 실패하면 실패로 표시하고 다음 작업으로 넘어간다(재계획 없음).

**b. 작업별 모듈 검색.** 노드 설명의 임베딩 유사도와 필요한 역할(날짜, 가격, 품종…)로 라이브러리를 거르고, LLM이 후보 중 `reuse | adapt | new`를 고른다. `status=verified` 모듈을 우선한다.

**c. 중간산출물 설계.** 각 노드가 만들 중간산출물의 형식을 먼저 정한다.

```json
{"artifacts": [
  {"id": "price_trend", "kind": "table", "description": "품종별 월평균가와 전년 대비 증감",
   "columns": [{"name": "월", "dtype": "date"}, {"name": "품종", "dtype": "str"}, {"name": "평균가", "dtype": "float", "unit": "원/kg"}]},
  {"id": "volatility", "kind": "metrics", "description": "품종별 가격 변동계수"}
]}
```

`kind`: `table | metrics | series | geo` (geo = 좌표와 속성, 지도용)

**d. 코드 계약.** 생성 코드는 반드시 이 형태를 따른다.

```python
MANIFEST = {
    "title": "...", "description": "검색용 설명", "tags": ["price"],
    "input_roles": {"prices": {"date": "date", "variety": "str", "price": "float"}},
    "params": {"months": "int"},
    "outputs": ["price_trend", "volatility"],
}

def run(inputs: dict[str, "pd.DataFrame"], params: dict) -> dict:
    """inputs의 컬럼은 역할 이름으로 이미 바뀌어 들어온다."""

def check(outputs: dict, inputs: dict) -> list[str]:
    """문제 목록을 반환. 빈 리스트면 통과."""
```

- 실행 직전에 LLM이 낸 **역할 매핑** `{"date": "거래일자", "price": "평균가", ...}`으로 컬럼 이름을 바꿔서 넣는다. 그래서 같은 모듈을 컬럼 이름이 다른 데이터에도 쓸 수 있다.

**e. 검증 순서.**

1. 정적 검사: 문법, import 허용 목록(`pandas numpy scipy math statistics datetime jejukit`), 금지 호출(`os.system`, `subprocess`, `socket`, `eval`, `exec`, 출력 폴더 밖 쓰기).
2. **mock test**: Profile로 가짜 데이터프레임 생성(타입, 범위, 결측률, 샘플 값 반영) → 실행 → 출력이 설계한 스키마와 맞는지, `check()` 통과하는지. *잡는 것: 오류, 형식 불일치. 못 잡는 것: 계산이 맞는지.*
3. 실데이터 실행 → `check()` + 공통 검사(빈 결과 금지, 전부 NaN 금지, 카탈로그 단위 기준의 상식 범위).
4. 실패하면 실패를 분류하고 **2차에서 실패 원인에 맞게 한 번 수정**한다. 그래도 실패하면 작업 실패. 2차 코드가 1차와 같으면 실행하지 않고 실패 처리. 데이터 문제로 분류되면 2차 없이 바로 실패. 상세: [docs/agent-flow.md](docs/agent-flow.md) "2차 수정 방법". 실패한 작업은 무엇을 하려 했고 왜 실패했는지 최종 산출물에 적는다.

**f. 실행 격리.** 별도 프로세스(`python -I runner.py`), 제한시간 60초, 작업 폴더는 해당 실행 폴더, 환경변수에서 API 키 제거, 소켓 차단. *주의: 악의적 코드를 막는 보안 샌드박스가 아니라 LLM 실수를 막는 장치다.* 기획서 한계에 적는다.

### ⑤ save_module — 재사용 저장

```
modules/
  index.json
  market_trend.price_volatility/
    v1/
      module.py
      manifest.json   # 제목, 설명(검색용), 태그, 입력 역할, 출력 스키마, params,
                      # 검증 기록(mock/real 통과), 테스트한 데이터 id+version_hash,
                      # 생성 모델, 생성일, 원 요청 목표(개인정보 제거)
```

- `status`: `verified`(사람이 검토, 기본 탑재) / `auto`(자동 저장). 검색 시 `verified` 우선.
- 데이터 `version_hash`가 바뀌면 캐시된 **결과**는 버리고 **코드**는 다시 검증해서 쓴다.
- 기본 탑재 모듈(대표 질문용)을 미리 만들어 넣는다. 심사위원이 LLM 코드 생성 없이도 재현할 수 있게.

### ⑥ render — 최종 산출물

**a. ReportSpec (LLM, Structured Outputs).**

```json
{
  "title": "...", "summary": "3문장 이내",
  "sections": [
    {"heading": "...", "body": "설명 문장",
     "blocks": [
       {"type": "chart", "artifact_id": "price_trend", "chart": "line"},
       {"type": "map", "artifact_id": "site_points"},
       {"type": "diagram", "mermaid": "flowchart LR ..."},
       {"type": "table", "artifact_id": "volatility"},
       {"type": "callout", "tone": "warning", "text": "..."}
     ]}
  ],
  "limitations": ["..."]
}
```

**b. 숫자 근거 대조.** 본문의 숫자를 뽑아서 Artifact 값과 대조(반올림 허용). 근거 없는 숫자가 있는 문장은 바로 제거한다.

**c. 형식별 템플릿** (Jinja2, 하나의 독립 HTML 파일로 저장):

| 형식 | 언제 | 구성 |
|---|---|---|
| `report` | 보고서를 원할 때 | 요약 → 방법 → 결과(표·차트) → 한계 → 출처 |
| `visual` | 쉽게 설명을 원할 때 | 큰 결론 한 줄 → 흐름도(Mermaid) → 단순 차트 → 쉬운 말 설명 |
| `map` | 공간 정보가 필요할 때 **(무조건)** | 지도(Leaflet/folium)가 중심 + 옆에 요약·차트 |

- 모든 형식에 공통으로 넣는 것: **사용한 데이터 / 제외한 데이터와 이유**(②에서), **분석 과정**(쓴 모듈 id와 버전), **근거와 한계**, 데이터 출처·이용조건.
- 라이브러리는 CDN으로 로드: Chart.js, Mermaid, Leaflet.

---

## 3. 데이터 카탈로그 (오프라인으로 미리 구축)

`catalog/{dataset_id}.json`:

```json
{
  "id": "jdh_agri_daily_trade",
  "title": "농산물 품종별 일일 거래 정보",
  "source": "제주데이터허브", "access": "api", "license": "...",
  "spatial_unit": "point | grid | 읍면동 | 시군구 | 시도 | none",
  "temporal_unit": "day", "coverage": {"from": "...", "to": "...", "region": "제주"},
  "columns": [{"name": "평균가", "meaning": "...", "unit": "원/kg", "role_hint": "price"}],
  "notes": "알려진 한계"
}
```

- 구축: `profile()` 자동 실행 → LLM이 컬럼 의미 초안 작성 → **사람이 1회 검수**.

### 3.1 데이터 현황 (2026-11-07)

| 데이터 | 출처 | 공간 단위 | 확인된 사항 | 남은 문제 |
|---|---|---|---|---|
| 농산물 품종별 일일 거래 통계 | 허브 (API) | 없음(시장) | 필수: startDate·endDate·cultivar, 페이지당 100건. 필드 baseDate·cultivar·averagePrice(평균 도매가격, 원/kg)·transactionVolume(거래량, 톤)·transactionAmount(거래금액, 백만원). 품종 18개(당근·마늘·무·양배추·양파) | 어느 시장인지 미기재, 숫자가 문자열 |
| 농산물 품종별 거래 이동평균 | 허브 (API) | 없음(시장) | 위와 같음 + period(1·2·7·30·90). 필드 priceMovingAverage(원/kg)·volumeMovingAverage(톤)·amountMovingAverage(백만원) | 위와 같음, **결측이 0.00으로 옴** |
| 서귀포시 감귤 생산 정보 | 허브 (CSV) | 읍면동 | cp949, 2012~2022, 서귀포시 15개 읍면동 × 농가수·면적(ha)·생산량(톤) × 감귤 7종(넓은 형식) | **제주시 없음**(대체 데이터도 없음), 읍면동 경계 데이터 필요 |
| 일별 도·소매 가격 (KAMIS) | 공공데이터포털 (외부 API) | 시군구/시장 | serviceKey 필요, 페이지당 1,000건, kg 환산가 제공. 표준코드 API 명세 확보(단위·크기·도매시장·법인·산지·포장·등급·품목 코드) | 표준코드의 상품 대·중·소분류 코드가 가격 API의 부류·품목·품종 코드와 같은 체계인지 미확인, 시군구 코드 조회 오퍼레이션 없음 |
| DEM 90m | 국토지리정보원 (외부) | 격자 | 도엽 6장(.img, float32, EPSG:5179, nodata -9999), 본섬 전체 | 바다가 nodata 아님(값 있음) → 바다 마스크 필요, 도엽 병합 필요, 이용조건 미확인 |
| 기상 관측 | 기상청 (외부) | 관측소 | **확정: 지상(방재, AWS) 조회서비스**(제주 약 37개소, 산지 관측소 포함) + 지점정보 조회(위경도·고도, 고도 보정용). 무료, 개발계정 하루 10,000건. ASOS는 사용하지 않음 | 키 미발급, 10년치 일자료 일괄 수집·스냅샷 필요, 실제 제공 지점·기간 확인 필요 |
| 작목 재배 조건 | 문헌 (수작업 표) | — | 감귤: 감귤연구소 적지 기준(연평균기온 14.5℃ 이상, 극최저 -10℃ 이상, -5℃ 이하 저온일수). 무: 생육적온 17~23℃, 다 자란 무 0℃ 내외 동해(제주농업기술원) | 감귤 저온일수 기준 원문 확인 필요, **당근·양배추·마늘·양파 수치 미확보** |

- 제주시 지점에서 감귤을 물으면 "서귀포시 데이터만 있어 생산 현황은 답할 수 없음"을 표시하고 기후·고도·시세로만 판단한다 (§② `infeasible_parts`).
- ②에는 `title, source, spatial_unit, temporal_unit, coverage, columns(이름·의미·단위)`만 보낸다.

---

## 4. 실행 기록 (trace)

`runs/{run_id}/trace.json`: 단계별 입력·출력, LLM 호출(모델, 프롬프트 해시, 토큰, 시간), 선택·제외 결정, 코드 시도 횟수와 실패 이유. UI의 "탐색 로그"와 기획서의 실행 결과 자료로 쓴다.

---

## 5. 평가 계획

| 대상 | 방법 | 지표 |
|---|---|---|
| ① 규격화 | 질문 30~50개 + 정답 `needs`·형식·되묻기 여부·도메인 판정. 시험지에는 대표 유형 외에 **처음 보는 조합의 질문**도 넣는다 | 정확도 |
| ② 선택 | 같은 질문 + 반드시 포함/제외할 데이터, 불가 여부 | 포함 재현율, 제외 정확도, 불가 판정 정확도 |
| ④ 코드 | 위 질문 실행 | 1회 성공률, 3회 내 성공률, mock 통과 후 실데이터 실패율 |
| ⑥ 렌더 | 숫자 근거 대조 | 근거 없는 숫자 비율 |
| 재현성 | 기본 탑재 모듈 + 데이터 스냅샷 | 같은 입력 → 같은 Artifact |

LLM 호출은 `temperature=0`, `seed` 고정. 설명 문장은 달라질 수 있음을 한계에 적는다.

---

## 6. 열린 질문

1. 기본 탑재(verified) 모듈로 미리 만들어 둘 대표 분석 목록 (경로 제한이 아니라 재현성·속도용)
2. 허브 데이터 실제 스키마 (HWP 문서 → HWPX/DOCX로 변환해 받기로)
