# 10: DEM 고도 조회 + 바다·범위 밖 판정

**What to build:** 클릭한 지점의 고도가 나오고 바다나 제주 본섬 밖을 클릭하면 범위 밖 안내가 나온다. `data/(B080)공개DEM_*` 도엽 6장(.img, 90m, EPSG:5179, nodata -9999)을 병합해 쓴다. 이 DEM은 **바다가 nodata가 아니라 값이 들어 있으므로 바다 마스크가 필요**하다. 경사·사면·일사 모델링은 하지 않는다. 지리 패키지의 DEM 부분을 소유한다. 읽을 것: `.scratch/jeju-agri-agent/spec.md`의 DEM 항목.

**Blocked by:** 02

**Status:** done

- [x] 도엽 6장을 하나의 격자로 병합하고 위경도 입력을 EPSG:5179로 변환해 고도를 조회하는 도구 `get_elevation(lat, lon)`이 있다
- [x] 바다 마스크: 해안선 기준으로 바다 칸을 판정한다. 기준(예: 0m 이하 + 육지 연결성 등)과 한계를 문서에 적는다
- [x] 바다·본섬 밖(추자도 등) 좌표는 범위 밖으로 판정되고, 02의 대략적 경계 검사를 이 판정으로 대체한다
- [x] 알려진 지점(한라산 정상 약 1,950m, 해안 등)에서 고도가 상식 범위인지 확인하는 테스트가 있다
- [x] 고정 도구 라이브러리에 등록되어 생성 코드에서 import할 수 있다
- [x] 병합 결과는 캐시되어 두 번째 실행부터 빠르다
- [x] 자동 테스트: 지점 고도, 바다 판정, 범위 밖 판정, 도엽 경계 지점

## Comments
- `.cache/dem/`가 `.gitignore`에 없다. 사용자가 `.cache/`를 추가해 주세요 (소유 밖이라 수정하지 않음).
- "고정 도구 라이브러리 등록"은 05가 `rasterio`/`pyproj` import를 막으므로 생성 코드가 직접 쓰는 방식이 아니라 부모가 값을 미리 계산해 넘기는 방식으로 충족했다 (아래 Result).

## Result

- 만든 것: `backend/jejuagent/geo/dem.py`, `geo/__init__.py`, `backend/tests/geo/test_dem.py`, `docs/dem.md`. `runner/request_plan.py`의 `out_of_range`만 교체(DEM 판정, 파일 없으면 bbox 폴백 + 로그 경고).
- 인터페이스(12용): `from jejuagent.geo import get_elevation, is_land, elevation_grid_info, out_of_range_message`. `get_elevation(lat, lon) -> float|None`(m, 최근접 90m, 바다·격자 밖은 None), `is_land(lat, lon) -> bool`, `out_of_range_message`는 DEM 없으면 `FileNotFoundError`. 첫 호출 때 병합·캐시(`.cache/dem/merged.npz`, 서명 불일치 시 재생성), 이후 약 0.08초.
- 테스트: `pytest backend/tests/geo backend/tests/runner backend/tests/parse` 26개 통과(키·네트워크 없음). 지점 고도, 바다, 격자 밖(추자도·마라도), 도엽 경계, 캐시 속도·무효화, DEM 없을 때 폴백.
- 실측: 격자 최고 1,938m(33.360N 126.530E), 성산 인근 약 96m, 서귀포 시가지 약 71m, 제주시 해안 약 1.3m.
- 바다 마스크: 고도 > 1.0m인 연결 성분 중 100칸 이상을 육지로 본다. 육지 약 1,851km2로 본섬 면적과 맞는다. 한계(해안 저지대·항만 오판, 90m 오차, 우도·가파도는 육지로 판정, 마라도·추자도는 격자 밖, 해안선 완벽하지 않음)는 `docs/dem.md`에 적었다.
- 생성 코드 연결: 05 허용 목록에 rasterio/pyproj가 없으므로 부모(단계 코드)가 미리 `elevation_m`, `is_land`를 계산해 데이터로 넘기는 방식을 권장한다.
