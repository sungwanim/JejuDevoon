# 지점 기후 추정 (티켓 12)

코드: 계산 전부 `backend/jejuagent/modules_seed/site/site_climate.py`(verified 모듈 소스, 코드 계약 `MANIFEST/run/check`, numpy/pandas만). 부모 쪽 얇은 층은 `geo/climate.py`(`estimate_site`, `site_inputs`, `limitations`), 

## 입력 표준 스키마 (사용자가 AWS 일자료를 이 형식으로 변환한다)
실제 API·CSV 형식은 확인된 적이 없어 변환기는 없다.
- `aws`(관측소 x 일 한 행): `station`(str) `lat` `lon` `elevation_m`(m) `date` `tmean` `tmin` `tmax`(현재 미사용) `precip`(mm). 기온 ℃. 관측소 좌표·고도는 관측소별로 같아야 한다(첫 행 사용).
- `site`(1행): `lat` `lon` `elevation_m`. 격리 프로세스는 rasterio를 못 쓰므로 부모가 `get_elevation`으로 미리 구해 넘긴다(`site_inputs`). 바다·격자 밖이면 `ValueError`(안내문).
- 파라미터: `lapse_c_per_km`(6.5), `idw_power`(2), `growing_months`("10,11,12,1,2,3").

## 방법
1. 관측소 값 + 감률 x 고도 = 해면 환산값. 2. 해면 환산값을 IDW(거리^-2, 결측 관측소는 그날만 제외)로 지점에 보간. 3. 지점 고도 x 감률을 빼서 되돌림. 일 단위로 추정한 뒤 지표를 집계한다. 거리는 위경도 근사(km). 강수량은 고도 보정 없이 IDW.
- **감률: 고정 6.5℃/km 기본.** 근거는 Ryu 외 2024가 제주 기본값으로 쓴 값. 실데이터로 검증하지 못했다. 관측소 수가 적고 겨울 역전층이 있으면 적합 감률이 불안정할 수 있어 기본을 고정으로 했다. 대신 교차검증이 "관측소 고도 회귀로 적합한 감률(`idw_lapse_fitted`, 빼고 남은 관측소로 적합)"을 같이 보고하므로 실데이터에서 비교해 `lapse_c_per_km`을 바꾼다.
- **보간: IDW.** 관측소 수가 적고 값을 덮어쓰지 않으며(외삽에서 튀지 않음) 결측일 처리가 쉽다. 논문은 잔차 보간에 RBF 등을 썼다. RBF가 더 나은지는 **미확인**이다(실데이터 필요).
- 지표: 연평균기온(일평균 평균), 극최저기온(일최저 최솟값), -5℃·0℃ 이하 일수(일최저 기준, 연평균 일수), 생육기간 평균기온(`growing_months`의 일평균 평균. 월 기본값은 월동 채소 중심 가정이며 기준표 작형을 읽지 않는다), 강수량(연). 관측기간이 1년 미만이면 연 지표가 계절 편향이므로 `n_years`를 확인한다.
- **한계온도 판정은 하지 않는다.** 극최저·-5℃·0℃ 일수는 참고 지표(`reference_note`)일 뿐이고 합격/불합격·'한계 초과' 문구가 없다.

재배 적합도는 판정하지 않는다(공공데이터 근거 없음, 문헌 기준표 기능은 제거했다).

## 교차검증
관측소를 하나씩 빼고 그 관측소의 일 tmean·tmin을 추정, 관측소 평균 MAE(`mae_daily_c`)와 기간 평균 오차(`mae_period_mean_c`)를 방법별로 낸다: `idw_lapse_fixed`, `idw_lapse_fitted`, `idw_no_elevation`, `nearest_station`.
실데이터(농업기상 제주 16개 관측소, 고도 18~208m)로 계산한 오차다. 관측소가 저지대 농경지 위주라 한라산 고지대의 오차는 이 값으로 알 수 없다.

## 산출물 (kind)
`site_markers`(geo: name, role=site|station, lat, lon, elevation_m, annual_mean_c), `site_indicators`(metrics), `cross_validation`(table), `limitations`(table, 컬럼 `text`). 08 `map` 템플릿 연결은 하지 않았다(마커 컬럼 이름은 위와 같다).

## 한계 문구 (렌더 단계가 쓰도록)
데이터: `site_climate.LIMITATIONS` 리스트. 접근: `jejuagent.geo.climate.limitations()` 또는 모듈 출력 `limitations` 표의 `text`. 결과에는 자동으로 들어 있다(90m DEM, 경사·일사 미반영, 관측소 밀도, 강수 보정 없음, 한계온도 판정 안 함, 기준 근거 부족 처리). 렌더는 이 문구들을 결과 옆에 그대로 보이면 된다.

## 실데이터를 가져오는 방법
`collect agri-weather`(농촌진흥청 농업기상)가 위 표준 컬럼으로 `snapshots/live/jeju_weather_daily.json`을 만든다(README 참고). 기간은 가능하면 여러 해 전체 연도가 좋다. 수집 후 `estimate_site(df, lat, lon)`로 `cross_validation`을 확인하고, 겨울 오차가 크면 `lapse_c_per_km`을 적합값으로 바꿔 다시 비교한다.
