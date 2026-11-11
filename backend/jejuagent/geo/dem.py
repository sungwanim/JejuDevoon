"""DEM 고도 조회와 바다·범위 밖 판정 (티켓 10).

도엽 6장(90m, EPSG:5179)을 하나의 격자로 병합하고 바다 마스크를 만든 뒤 .cache/dem/ 에 캐시한다.
- 병합: 모든 도엽이 90m 격자에 정렬돼 있고 겹치는 칸의 값이 서로 같다(실측 차이 0). 그래서 보간 없이
  빈 칸(NaN)만 채우는 방식으로 붙인다. 도엽이 없는 모서리는 NaN(= 격자 밖).
- 보간: 최근접. 칸 값 자체가 90m 평균이고, 쌍선형은 해안에서 바다 값(0 근처)과 섞여 마스크와 어긋난다.
- 바다 마스크: 바다 칸에도 값이 있다(대부분 정확히 0, 일부 -9.7~+1 잡음). 고도 > LAND_MIN_M(1.0m)인 칸 중
  연결 성분 크기 >= MIN_LAND_CELLS(100칸, 약 0.8km2)만 육지로 본다. 한계는 docs/dem.md 참고. 완벽한 해안선이 아니다.
"""
from __future__ import annotations

import glob
import json
import logging
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[3]
DATA_GLOB = "data/(B080)공개DEM_*/*/*.img"
CACHE_DIR = ROOT / ".cache" / "dem"
LAND_MIN_M = 1.0
MIN_LAND_CELLS = 100
RES = 90.0
_state: dict = {}


def _files() -> list[Path]:
    return sorted(Path(p) for p in glob.glob(str(ROOT / DATA_GLOB)))


def _signature(files: list[Path]) -> str:
    return json.dumps([[f.name, f.stat().st_size, f.stat().st_mtime_ns] for f in files]
                      + [LAND_MIN_M, MIN_LAND_CELLS])


def _build(files: list[Path]) -> dict:
    import rasterio
    import scipy.ndimage as nd
    tiles = []
    for f in files:
        with rasterio.open(f) as s:
            a = s.read(1).astype("float32")
            a[a == (s.nodata if s.nodata is not None else -9999)] = np.nan
            tiles.append((s.bounds, a))
    left = min(b.left for b, _ in tiles); top = max(b.top for b, _ in tiles)
    right = max(b.right for b, _ in tiles); bottom = min(b.bottom for b, _ in tiles)
    grid = np.full((round((top - bottom) / RES), round((right - left) / RES)), np.nan, np.float32)
    for b, a in tiles:
        r, c = round((top - b.top) / RES), round((b.left - left) / RES)
        sub = grid[r:r + a.shape[0], c:c + a.shape[1]]
        fill = np.isnan(sub)
        sub[fill] = a[fill]
    lab, _ = nd.label(np.nan_to_num(grid, nan=-9999) > LAND_MIN_M)
    sizes = np.bincount(lab.ravel()); sizes[0] = 0
    land = (sizes >= MIN_LAND_CELLS)[lab]
    return {"grid": grid, "land": land, "origin": np.array([left, top])}


def _load() -> dict | None:
    """병합 격자를 돌려준다. DEM 파일이 없으면 None(호출자가 bbox로 폴백)."""
    if "d" in _state:
        return _state["d"]
    files = _files()
    d = None
    if not files:
        log.warning("DEM 도엽 파일이 없어 bbox 판정으로 폴백한다 (%s)", ROOT / DATA_GLOB)
    else:
        sig, cache = _signature(files), CACHE_DIR / "merged.npz"
        try:
            with np.load(cache) as z:
                if str(z["sig"]) == sig:
                    d = {k: z[k] for k in ("grid", "land", "origin")}
        except Exception:
            pass
        if d is None:
            d = _build(files)
            try:
                CACHE_DIR.mkdir(parents=True, exist_ok=True)
                np.savez(cache, sig=sig, **d)  # 압축 안 함: 읽기 속도 우선
            except OSError as e:
                log.warning("DEM 캐시 저장 실패: %s", e)
    _state["d"] = d
    return d


def _cell(lat: float, lon: float):
    d = _load()
    if d is None:
        return None
    if "tf" not in _state:
        from pyproj import Transformer
        _state["tf"] = Transformer.from_crs(4326, 5179, always_xy=True)
    x, y = _state["tf"].transform(lon, lat)
    c, r = int(np.floor((x - d["origin"][0]) / RES)), int(np.floor((d["origin"][1] - y) / RES))
    if 0 <= r < d["grid"].shape[0] and 0 <= c < d["grid"].shape[1] and not np.isnan(d["grid"][r, c]):
        return d, r, c
    return None


def is_land(lat: float, lon: float) -> bool:
    """제주 본섬(과 격자에 든 우도 등)의 육지 칸이면 True. 격자 밖·바다는 False. DEM 없으면 False."""
    h = _cell(lat, lon)
    return bool(h and h[0]["land"][h[1], h[2]])


def get_elevation(lat: float, lon: float) -> float | None:
    """해발고도(m, 최근접 90m 칸). 격자 밖이거나 바다 칸이면 None."""
    h = _cell(lat, lon)
    return float(h[0]["grid"][h[1], h[2]]) if h and h[0]["land"][h[1], h[2]] else None


def elevation_grid_info() -> dict | None:
    d = _load()
    return None if d is None else {"shape": d["grid"].shape, "land_cells": int(d["land"].sum()),
                                   "origin_epsg5179": tuple(float(v) for v in d["origin"]), "res_m": RES}


def out_of_range_message(lat: float, lon: float) -> str | None:
    """안이면 None, 밖이면 안내문. DEM 파일이 없으면 FileNotFoundError(호출자가 bbox로 폴백)."""
    if _load() is None:
        raise FileNotFoundError("DEM 없음")
    if is_land(lat, lon):
        return None
    return f"선택한 위치({lat:.3f}, {lon:.3f})는 바다이거나 제주 본섬 범위 밖입니다. 제주 본섬 육지에서 위치를 다시 골라 주세요."
