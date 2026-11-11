"""모듈 메타데이터의 개인정보 제거 규칙. 원 요청 목표(goal)·제목·설명에 적용하고, 코드에는 위반이 있으면 저장을 거부한다.

제거 대상: 이메일, 전화번호, 좌표(제주 부근 위경도 소수), API 키·토큰·비밀번호, 긴 토큰 문자열, 지번 주소,
'성+이름+호칭' 형태의 사람 이름과 '이름:' 같은 라벨 뒤의 이름.
한계: 이름은 휴리스틱(성씨 + 1~2글자 + 씨/님/사장/조합장 등)이라 호칭 없는 이름은 못 잡는다. 알려진 이름은 `extra`로 넘긴다.
"""
from __future__ import annotations

import re

_SUR = "김이박최정강조윤장임한오서신권황안송류전홍고문양손배백허유남심노하곽성차주우구민진지엄채원천방공현함변염여추도소석선설마길연위표명기반왕금옥육인맹제모탁국어은편용예경봉사부"
_COORD = r"(?<![\d.])(?:3[2-9]|12[4-9]|13[0-2])\.\d{3,}(?!\d)"
_SECRET_KW = r"(?:api[_-]?key|service[_-]?key|project[_-]?key|token|secret|password|passwd)"

RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), "[이메일]"),
    (re.compile(r"(?<!\d)0\d{1,2}[-. ]?\d{3,4}[-. ]?\d{4}(?!\d)"), "[전화]"),
    (re.compile(rf"(?i)\b({_SECRET_KW})\b\s*[=:]\s*[^\s,;&]+"), r"\1=[제거]"),
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}"), "[키]"),
    (re.compile(r"\b(?=\w*\d)(?=\w*[A-Za-z])\w{32,}\b"), "[키]"),
    (re.compile(_COORD), "[좌표]"),
    (re.compile(r"\d+(?:-\d+)?\s*번지"), "[주소]"),
    (re.compile(r"((?:이름|성명|농가주|농업인)\s*[:=]?\s*)[가-힣]{2,4}"), r"\1[이름]"),
    (re.compile(rf"(?<![가-힣])[{_SUR}][가-힣]{{1,2}}(?=\s*(?:씨|님|농장주|조합장|사장))"), "[이름]"),
]
_CODE_PII = [re.compile(_COORD), re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}"),
             re.compile(rf"(?i){_SECRET_KW}\w*\s*=\s*[\"'][^\"']{{6,}}[\"']"),
             re.compile(r"[\"'](?=\w*\d)(?=\w*[A-Za-z])\w{32,}[\"']")]


def scrub(text: str, extra: list[str] | None = None) -> str:
    for name in extra or []:
        if name:
            text = text.replace(name, "[이름]")
    for pat, rep in RULES:
        text = pat.sub(rep, text)
    return text


def code_has_pii(code: str) -> bool:
    """코드 안에 좌표 리터럴이나 키·토큰 리터럴이 있으면 True (그런 코드는 모듈로 저장하지 않는다)."""
    return any(p.search(code) for p in _CODE_PII)
