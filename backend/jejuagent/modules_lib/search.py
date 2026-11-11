"""모듈 검색: 작업 설명 유사도 + 필요한 역할 + 출력 개수. `verified`가 `auto`보다 먼저.

유사도는 교체 가능한 `Retriever`가 낸다. 기본은 외부 호출 없는 글자 2·3-gram TF-IDF 코사인(한국어에 형태소 분석기 없이 동작).
임베딩으로 바꾸려면 `scores(query, docs)`를 구현한 클래스(OpenAI 임베딩 호출 + 코사인)를 `ModuleStore(retriever=...)`에 넘기면 된다.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

VERIFIED_BONUS = 0.15      # 유사도가 비슷하면 verified가 이기게 하는 가산점
HINT_BONUS = 0.05          # 컬럼의 role_hint가 모듈 역할 이름과 일치한 비율에 곱함


class Retriever:
    def scores(self, query: str, docs: list[str]) -> list[float]:
        raise NotImplementedError


class NgramRetriever(Retriever):
    def __init__(self, ns=(2, 3)):
        self.ns = ns

    def _grams(self, text: str) -> Counter:
        t = re.sub(r"\s+", " ", text.lower())
        return Counter(t[i:i + n] for n in self.ns for i in range(len(t) - n + 1))

    def scores(self, query, docs):
        vecs = [self._grams(d) for d in docs]
        q = self._grams(query)
        df = Counter(g for v in vecs + [q] for g in v)
        n = len(vecs) + 1

        def weigh(v):
            return {g: c * (math.log((1 + n) / (1 + df[g])) + 1) for g, c in v.items()}

        wq = weigh(q)
        nq = math.sqrt(sum(x * x for x in wq.values())) or 1.0
        out = []
        for v in vecs:
            w = weigh(v)
            nd = math.sqrt(sum(x * x for x in w.values())) or 1.0
            out.append(sum(x * w.get(g, 0.0) for g, x in wq.items()) / (nq * nd))
        return out


@dataclass
class Candidate:
    module: object
    score: float
    sim: float
    binding: dict          # 제안하는 {모듈 입력 이름: 작업 입력 이름}


_NUM = {"int", "float"}


def _fits(want: str, have: str) -> bool:
    return want == have or {want, have} <= _NUM


def bind(module, profiles: dict) -> tuple[dict, float] | None:
    """모듈의 입력마다 필요한 역할(dtype)을 채울 수 있는 작업 입력을 하나씩 배정한다. 못 채우면 None.
    반환: (배정, role_hint 일치 비율)."""
    used, binding, hits, total = set(), {}, 0, 0
    for mi, roles in module.input_roles.items():
        for ti, prof in profiles.items():
            if ti in used:
                continue
            taken, ok, h = set(), True, 0
            for role, dt in roles.items():
                free = [c for c in prof["columns"] if c["name"] not in taken and _fits(dt, c["dtype"])]
                c = next((c for c in free if c.get("role_hint") == role), None) or (free[0] if free else None)
                if c is None:
                    ok = False
                    break
                taken.add(c["name"])
                h += c.get("role_hint") == role
            if ok:
                binding[mi] = ti
                used.add(ti)
                hits, total = hits + h, total + len(roles)
                break
        else:
            return None
    return binding, hits / max(total, 1)


def doc(m) -> str:
    return f"{m.title} {m.description} {' '.join(m.tags)}"


def search(store, query: str, profiles: dict, n_outputs: int | None = None, k: int = 3,
           min_sim: float = 0.1) -> list[Candidate]:
    mods = store.all()
    if not mods:
        return []
    sims = store.retriever.scores(query, [doc(m) for m in mods])
    out = []
    for m, sim in zip(mods, sims):
        if sim < min_sim or (n_outputs is not None and len(m.outputs) != n_outputs):
            continue
        b = bind(m, profiles)
        if b is None:
            continue
        score = sim + (VERIFIED_BONUS if m.status == "verified" else 0.0) + HINT_BONUS * b[1]
        out.append(Candidate(m, score, sim, b[0]))
    return sorted(out, key=lambda c: -c.score)[:k]
