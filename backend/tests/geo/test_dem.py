import numpy as np
import pytest

from jejuagent.geo import dem
from jejuagent.runner.request_plan import out_of_range

HAVE_DEM = bool(dem._files())
needs_dem = pytest.mark.skipif(not HAVE_DEM, reason="DEM 도엽 없음")


@pytest.fixture(autouse=True)
def fresh(monkeypatch, tmp_path):
    monkeypatch.setattr(dem, "CACHE_DIR", tmp_path / "dem")
    monkeypatch.setattr(dem, "_state", {})


@needs_dem
def test_summit_and_inland():
    assert 1850 <= dem.get_elevation(33.3600, 126.5300) <= 1940   # 격자 최고 1938m 부근
    assert 1500 < dem.get_elevation(33.362, 126.533) < 1940       # 백록담 인근
    assert 50 < dem.get_elevation(33.4580, 126.9425) < 200        # 성산일출봉 인근(실제 약 180m, 90m 평균)
    assert 50 < dem.get_elevation(33.2530, 126.5600) < 150        # 서귀포 시가지 인근


@needs_dem
def test_coast_and_sea():
    assert dem.is_land(33.5170, 126.5300) and dem.get_elevation(33.5170, 126.5300) < 20  # 제주시 해안
    assert not dem.is_land(33.53, 126.53)     # 제주항 앞 바다(값 0.3~0.7m 잡음이 있는 칸)
    assert dem.get_elevation(33.20, 126.56) is None   # 서귀포 앞바다


@needs_dem
def test_outside_grid_and_islands():
    assert dem.get_elevation(33.95, 126.30) is None   # 추자도: 격자 밖
    assert not dem.is_land(33.1143, 126.27)           # 마라도: 격자 밖
    assert dem.is_land(33.50, 126.95)                 # 우도: 격자 안, 육지로 판정(문서화된 선택)
    assert out_of_range(33.95, 126.30) is not None
    assert out_of_range(33.53, 126.53) is not None
    assert out_of_range(33.4, 126.5) is None


@needs_dem
def test_tile_seams():
    """도엽 경계(겹침 구간)를 가로지르는 선에서 육지 칸이 모두 값이 있고 이웃 칸과 급변하지 않는다."""
    d = dem._load()
    g, land = d["grid"], d["land"]
    # 6장 경계 x(EPSG:5179) = 906930/907740(33606|33607), 930150/930870(33607|33608), 마주보는 위아래 y=1490040~1490490
    for x in (907000, 930500):
        c = int((x - d["origin"][0]) // 90)
        col = g[:, c]; m = land[:, c]
        assert not np.isnan(col[m]).any()
        assert np.nanmax(np.abs(np.diff(g[:, c - 1:c + 2], axis=1))[m]) < 150
    r = int((d["origin"][1] - 1490200) // 90)
    assert land[r].any() and not np.isnan(g[r][land[r]]).any()


@needs_dem
def test_cache_speed_and_invalidation(monkeypatch):
    import time
    dem._load()
    assert (dem.CACHE_DIR / "merged.npz").exists()
    dem._state.clear()
    t = time.time(); dem._load(); assert time.time() - t < 1.0   # 캐시 적중
    # 도엽 구성이 바뀌면 서명이 달라져 다시 만든다
    dem._state.clear()
    files = dem._files()
    monkeypatch.setattr(dem, "_files", lambda: files[:5])
    dem._load()
    assert dem.elevation_grid_info()["land_cells"] < 228000
    with np.load(dem.CACHE_DIR / "merged.npz") as z:
        assert str(z["sig"]) == dem._signature(files[:5])


def test_fallback_to_bbox_without_dem(monkeypatch, caplog):
    monkeypatch.setattr(dem, "_files", lambda: [])
    assert out_of_range(33.4, 126.5) is None
    assert out_of_range(33.95, 126.30) is not None   # bbox도 추자도는 거른다
    assert out_of_range(33.53, 126.53) is None       # bbox는 바다를 못 거른다(폴백의 한계)
    assert not dem.is_land(33.4, 126.5) and dem.get_elevation(33.4, 126.5) is None
    assert "폴백" in caplog.text
