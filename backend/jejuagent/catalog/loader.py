"""파일·스냅샷 로더. 인코딩 자동 판별, 숫자 문자열 변환, 결측 표기 처리."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from ..data import parse_dates, to_numeric


def read_csv_auto(path: str | Path) -> pd.DataFrame:
    """utf-8(BOM 허용)로 읽어 보고 실패하면 cp949. 쓴 인코딩은 df.attrs['encoding']."""
    for enc in ("utf-8-sig", "cp949"):
        try:
            df = pd.read_csv(path, encoding=enc)
            df.attrs["encoding"] = "utf-8" if enc == "utf-8-sig" else enc
            return df
        except UnicodeDecodeError:
            continue
    raise ValueError(f"인코딩을 판별할 수 없습니다: {path}")


def load_dataset(entry: dict, root: str | Path, snapshots_dir: str | Path) -> pd.DataFrame:
    """카탈로그 항목 하나를 읽어 정리한 DataFrame으로. entry에 file(루트 기준) 또는 snapshot(snapshots_dir 기준)이 있다.
    컬럼 정리는 카탈로그 컬럼의 parse 힌트: date | numeric | numeric_zero_missing."""
    if "file" in entry:
        df = read_csv_auto(Path(root) / entry["file"])
    elif "snapshot" in entry:
        raw = json.loads((Path(snapshots_dir) / entry["snapshot"]).read_text(encoding="utf-8"))
        df = pd.DataFrame(raw["data"])
        df.attrs["encoding"] = "utf-8"
        df.attrs["synthetic"] = bool(raw.get("meta", {}).get("synthetic"))
    else:
        raise ValueError(f"file 또는 snapshot이 없는 카탈로그 항목: {entry.get('id')}")
    enc = df.attrs["encoding"]
    for c in df.select_dtypes(exclude="number").columns:
        df[c] = df[c].astype(str).str.strip()        # '효돈동 ' 같은 공백 정리
    for c in entry.get("columns", []):
        if c["name"] not in df.columns:
            continue
        p = c.get("parse")
        if p == "date":
            df[c["name"]] = parse_dates(df[c["name"]])
        elif p in ("numeric", "numeric_zero_missing"):
            df[c["name"]] = to_numeric(df[c["name"]], zero_is_missing=p == "numeric_zero_missing")
    df.attrs["encoding"] = enc
    return df
