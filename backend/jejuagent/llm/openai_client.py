"""OpenAI 구현. temperature=0, seed 고정, Structured Outputs. 키는 환경변수(.env)에서만 읽는다."""
from __future__ import annotations

import json
import os
import re
import time

from .base import CallInfo, LLMClient, LLMError, LLMResponse, prompt_hash

DEFAULT_MODEL = "gpt-4o"
SEED = 20261120


_KEY_LIKE = re.compile(r"sk-[A-Za-z0-9_\-*]+")   # sk-...(마스킹 별표 포함)


class OpenAILLM(LLMClient):
    def __init__(self, model: str = DEFAULT_MODEL, api_key: str | None = None, client=None):
        self.model = model
        self._api_key = api_key
        self._client = client  # 테스트에서 주입 가능. 없으면 첫 호출 때 만든다.

    def _get_client(self):
        if self._client is None:
            key = self._api_key or os.environ.get("OPENAI_API_KEY")
            if not key:
                raise LLMError("OPENAI_API_KEY가 없습니다. 프로젝트 루트의 .env에 OPENAI_API_KEY=... 를 넣어 주세요.")
            from openai import OpenAI
            self._client = OpenAI(api_key=key)
        return self._client

    # --- 요청 만들기 / 응답 읽기: 네트워크 없이 테스트하려고 분리 ---
    def build_kwargs(self, system: str, user: str, schema: dict | None = None,
                     schema_name: str = "result") -> dict:
        kw = dict(
            model=self.model,
            temperature=0,
            seed=SEED,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
        if schema is not None:
            kw["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": schema_name, "strict": True, "schema": schema},
            }
        return kw

    def _call(self, kwargs: dict, kind: str, purpose: str, phash: str) -> LLMResponse:
        t0 = time.monotonic()
        try:
            resp = self._get_client().chat.completions.create(**kwargs)
        except LLMError:
            raise
        except Exception as e:  # 네트워크·키 오류 등
            raise LLMError(f"OpenAI 호출 실패: {type(e).__name__}: {_KEY_LIKE.sub('sk-***', str(e))}") from e   # 401 메시지에 마스킹된 키 조각이 들어온다
        return self.parse_response(resp, kind, purpose, phash, int((time.monotonic() - t0) * 1000))

    def parse_response(self, resp, kind: str, purpose: str, phash: str, ms: int = 0) -> LLMResponse:
        msg = resp.choices[0].message
        if getattr(msg, "refusal", None):
            raise LLMError(f"모델이 응답을 거절했습니다: {msg.refusal}")
        usage = getattr(resp, "usage", None)
        info = CallInfo(kind, self.model, phash,
                        getattr(usage, "prompt_tokens", 0) or 0,
                        getattr(usage, "completion_tokens", 0) or 0, ms, purpose)
        content = msg.content or ""
        if kind == "text":
            return LLMResponse(info=info, text=content)
        try:
            return LLMResponse(info=info, data=json.loads(content))
        except json.JSONDecodeError as e:
            raise LLMError(f"구조화 응답이 JSON이 아닙니다: {e}") from e

    def structured(self, system, user, schema, *, schema_name="result", purpose=""):
        return self._call(self.build_kwargs(system, user, schema, schema_name),
                          "structured", purpose, prompt_hash(system, user, schema))

    def text(self, system, user, *, purpose=""):
        return self._call(self.build_kwargs(system, user), "text", purpose, prompt_hash(system, user))
