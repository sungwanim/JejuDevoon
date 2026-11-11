"""숫자 근거 대조 (티켓 08). LLM 문장 속 숫자가 중간산출물 값에서 온 것인지 확인하고, 아니면 그 문장을 제거한다.

규칙(문서화된 약속):
 1. 근거 집합 = 중간산출물의 모든 숫자 셀 + 열별 min/max/mean/median/sum/first/last/건수/고유값 수 + 첫값→끝값의 차이와 변화율(%)
    + 표 크기(행·열 수) + 사용자 요청·계획에 이미 있던 숫자 + 선택/제외/작업 개수. 절댓값 1.5 이하 값은 100배(%)도 근거로 본다.
 2. 반올림 허용: 글에 쓴 소수 자릿수만큼 반올림(또는 절반 단위 오차)해서 같으면 일치. '만/천/억/백만' 단위 접미는 환산해서 비교한다.
 3. 검사하지 않는 숫자: 연·월·일(2024년, 3월, 15일, 2024-01-15, 1~3월), 서수·세는 말(3문장, 1단계, 2번째, 1위, 3가지, 2주),
    목록 번호('1.' '2)'로 시작), 영문자가 붙은 식별자(task1, jdh_agri_2). 4자리 연도(1900~2099)는 소수점 없을 때만 면제.
 4. 검사에 걸린 숫자가 하나라도 있으면 그 문장 전체를 제거한다.
"""
from __future__ import annotations

import math
import re
from typing import Any

import pandas as pd

_ID = re.compile(r"[A-Za-z_][A-Za-z_0-9\-]*\d[\w\-]*")
_DATE = re.compile(r"\d{4}\s*[-./]\s*\d{1,2}(?:\s*[-./]\s*\d{1,2})?")
_LIST_NO = re.compile(r"^\s*\d+[.)]\s+")
_UNIT_EXEMPT = r"(?:년|월|일|번째|단계|문장|가지|순위|위|차|주|분기|세기)"
_NUM = re.compile(
    r"(?<![\w.])[-+]?\d[\d,]*(?:\.\d+)?"
    r"(?!\d|\.\d)"                                  # 백트래킹으로 숫자 일부만 잡지 않게
    rf"(?!\s*{_UNIT_EXEMPT})"                       # 2024년, 3월, 3문장 ...
    r"(?!\s*[~\-–]\s*\d+\s*" + _UNIT_EXEMPT + ")"   # 1~3월
)
_YEAR = re.compile(r"^(?:19|20)\d{2}$")
_SCALE = (("백만", 1e6), ("만", 1e4), ("천", 1e3), ("억", 1e8))
_SENT = re.compile(r"(?<=[.!?。])\s+|\n+")


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT.split(text or "") if s.strip()]


def extract_numbers(sentence: str) -> list[tuple[float, int]]:
    """검사 대상 숫자 [(값(단위 환산 후), 글에 쓴 소수 자릿수)]."""
    s = _LIST_NO.sub("", sentence)
    s = _DATE.sub(" ", s)
    s = _ID.sub(" ", s)
    out = []
    for m in _NUM.finditer(s):
        raw = m.group().replace(",", "")
        if _YEAR.match(raw.lstrip("+-")):
            continue
        dec = len(raw.split(".")[1]) if "." in raw else 0
        v = float(raw)
        tail = s[m.end():m.end() + 3].lstrip()
        for word, k in _SCALE:
            if tail.startswith(word):
                v, dec = v * k, 0
                break
        out.append((v, dec))
    return out


def _add(g: set[float], v: Any) -> None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return
    if math.isfinite(f):
        g.add(f)
        if abs(f) <= 1.5:
            g.add(f * 100)


def _flatten(v: Any, g: set[float]) -> None:
    if isinstance(v, dict):
        for x in v.values():
            _flatten(x, g)
    elif isinstance(v, (list, tuple)):
        for x in v:
            _flatten(x, g)
    elif not isinstance(v, (str, bytes, bool)) and v is not None:
        _add(g, v)


def grounded_numbers(artifacts: dict, extra_texts: list[str] = (), extra_numbers: list[float] = ()) -> set[float]:
    g: set[float] = set()
    for a in artifacts.values():
        val = getattr(a, "value", a)
        if isinstance(val, pd.DataFrame):
            _add(g, val.shape[0]), _add(g, val.shape[1])
            for c in val.columns:
                col = val[c]
                if pd.api.types.is_numeric_dtype(col) and not pd.api.types.is_bool_dtype(col):
                    s = col.dropna()
                    for x in s.head(5000):
                        _add(g, x)
                    if len(s):
                        for x in (s.min(), s.max(), s.mean(), s.median(), s.sum(), s.iloc[0], s.iloc[-1], len(s),
                                  s.iloc[-1] - s.iloc[0]):
                            _add(g, x)
                        if s.iloc[0]:
                            _add(g, (s.iloc[-1] / s.iloc[0] - 1) * 100)
                            g.add(abs((s.iloc[-1] / s.iloc[0] - 1) * 100))
                else:
                    _add(g, col.nunique())
        else:
            _flatten(val, g)
    for t in extra_texts:
        for v, _ in extract_numbers(t or ""):
            _add(g, v)
    for n in extra_numbers:
        _add(g, n)
    return g


def is_grounded(v: float, dec: int, g: set[float]) -> bool:
    tol = 0.5 * 10 ** -dec + 1e-9
    return any(abs(x - v) <= tol or abs(abs(x) - abs(v)) <= tol and v < 0 for x in g)


def check_sentence(sentence: str, g: set[float]) -> bool:
    return all(is_grounded(v, d, g) for v, d in extract_numbers(sentence))


def filter_text(text: str, g: set[float], removed: list[str]) -> str:
    """근거 없는 숫자가 든 문장을 뺀 문장열. 뺀 문장은 removed에 쌓는다."""
    keep = []
    for s in split_sentences(text):
        (keep if check_sentence(s, g) else removed).append(s)
    return " ".join(keep)
