"""작목 적합도 규칙 (티켓 12). 점수는 없다. 항목별 충족 여부와 근거 출처만 낸다.

읽는 기준: 연평균기온, 생육적온(작목 기준표의 항목 이름이 아래 ITEM_INDICATOR에 있는 것)만.
읽지 않는 기준: 동해·저온 한계온도, 극최저기온, 저온일수, 발아·화아분화·저장·pH·작형. (사용자 결정: 신뢰할 만한 한계온도 자료 없음)
'미확보' 행은 판정하지 않고 '근거 부족'으로 낸다. 비교 계산 자체는 모듈 소스(modules_seed/site/site_climate.py)의
evaluate_suitability 하나만 있다 (생성 코드 없이 격리 프로세스에서도 같은 규칙).
"""
from __future__ import annotations

import pandas as pd

from .loader import CROPS, load_criteria

# 기준표 항목 이름 -> 비교할 지표. 이 목록에 없는 항목은 읽지 않는다.
# 생육적온(낮)/(밤)/(지온)은 일평균 기온과 성격이 달라 뺀다. 무 '생육적온'(threshold_max 20)은 기술서 값 그대로 쓴다.
ITEM_INDICATOR = {
    "연평균기온": "annual_mean",
    "생육적온": "growing_mean",
    "생육온도": "growing_mean",
    "생육적온(지상부)": "growing_mean",
    "생육적온(재배 전기간)": "growing_mean",   # 마늘: 현재 '미확보' -> 근거 부족으로 나온다
}
COLUMNS = ["crop", "item", "stage", "indicator", "value_type", "min", "max", "unit", "status", "source_id",
           "source_title", "confidence", "location", "grade"]


def criteria_rows(crops=None, table=None) -> pd.DataFrame:
    """적합도에 쓸 기준 행(출처 제목 포함). crops=None이면 전 작목."""
    t = table or load_criteria()
    rows = []
    for crop in (crops or CROPS):
        for r in t.get(crop):
            if r.item not in ITEM_INDICATOR:
                continue
            s = t.source_of(r)
            rows.append({"crop": r.crop, "item": r.item, "stage": r.stage, "indicator": ITEM_INDICATOR[r.item],
                         "value_type": r.value_type, "min": r.min, "max": r.max, "unit": r.unit, "status": r.status,
                         "source_id": r.source_id or "", "source_title": s.title if s else "",
                         "confidence": r.confidence, "location": r.location or "", "grade": r.grade or ""})
    return pd.DataFrame(rows, columns=COLUMNS)


def evaluate(indicators: dict, crops=None, table=None) -> pd.DataFrame:
    """indicators(annual_mean_c, growing_mean_c 필요)를 기준 행과 비교한 표."""
    from ..geo.climate import seed_module
    return seed_module().evaluate_suitability(criteria_rows(crops, table), indicators)
