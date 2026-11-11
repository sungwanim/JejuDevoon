"""허브 가격 품종명 <-> 재배현황 작목명 매핑 (데이터 파일 crop_name_map.json, 이름이 같은 것만)."""
import json
from pathlib import Path

_PATH = Path(__file__).with_name("crop_name_map.json")


def crop_for_cultivar(cultivar: str) -> str | None:
    maps = json.loads(_PATH.read_text(encoding="utf-8"))["maps"]
    return next((m["crop"] for m in maps if m["price_cultivar"] == cultivar), None)
