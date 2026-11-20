"""LLM providers for the cross-check: OpenAI (primary) -> Gemini (fallback).

Each reviewer sends the same system/user prompts and JSON schema, returns an
LLMVerdict or None, and never raises. SDK clients are created lazily on first use,
so building the chain needs no network and no installed SDK.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Mapping, Optional, Sequence

from .config import RulesConfig
from .llm_reviewer import (
    VERDICT_SCHEMA,
    ClaudeReviewer,
    LLMVerdict,
    NullReviewer,
    ReviewCase,
    build_system_prompt,
    build_user_prompt,
)
from .models import DECISIONS

log = logging.getLogger(__name__)

DEFAULT_MODELS = {"openai": "gpt-5", "gemini": "gemini-3.8-flash", "claude": "claude-opus-5-5"}
KEY_VARS = {"openai": ("OPENAI_API_KEY",), "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
            "claude": ("ANTHROPIC_API_KEY",)}
MODEL_VARS = {"openai": "OPENAI_MODEL", "gemini": "GEMINI_MODEL", "claude": "CLAUDE_MODEL"}


def parse_verdict(text: Optional[str], provider: str, claim_id: str) -> Optional[LLMVerdict]:
    try:
        data = json.loads(text or "")
    except json.JSONDecodeError:
        log.warning("%s returned invalid JSON for %s", provider, claim_id)
        return None
    if not isinstance(data, dict) or data.get("decision") not in DECISIONS:
        log.warning("%s returned an invalid decision for %s", provider, claim_id)
        return None
    return LLMVerdict(data["decision"], list(data.get("sop_refs") or []), data.get("rationale", ""),
                      provider=provider)


class _BaseReviewer:
    name = ""

    def __init__(self, sop_text: str, cfg: RulesConfig, client=None, model: Optional[str] = None,
                 api_key: Optional[str] = None):
        self.system = build_system_prompt(sop_text, cfg)
        self.model = model or DEFAULT_MODELS[self.name]
        self._client, self._api_key = client, api_key

    @property
    def provider(self) -> str:
        return f"{self.name}:{self.model}"

    def review(self, case: ReviewCase) -> Optional[LLMVerdict]:
        try:
            text = self._call(build_user_prompt(case))
        except Exception as e:  # any provider failure -> next provider / code decision
            log.warning("%s failed for %s: %s: %s", self.provider, case.item.claim_id, type(e).__name__, e)
            return None
        if text is None:
            return None
        return parse_verdict(text, self.provider, case.item.claim_id)


class OpenAIReviewer(_BaseReviewer):
    name = "openai"

    def _call(self, user_prompt: str) -> Optional[str]:
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(api_key=self._api_key)
        resp = self._client.responses.create(
            model=self.model,
            instructions=self.system,
            input=user_prompt,
            text={"format": {"type": "json_schema", "name": "claim_verdict",
                             "schema": VERDICT_SCHEMA, "strict": True}},
        )
        if resp.status != "completed":
            log.warning("%s response status %s", self.provider, resp.status)
            return None
        return resp.output_text


class GeminiReviewer(_BaseReviewer):
    name = "gemini"

    def _call(self, user_prompt: str) -> Optional[str]:
        if self._client is None:
            from google import genai
            self._client = genai.Client(api_key=self._api_key)
        resp = self._client.models.generate_content(
            model=self.model,
            contents=user_prompt,
            config={"system_instruction": self.system,
                    "response_mime_type": "application/json",
                    "response_json_schema": VERDICT_SCHEMA},
        )
        return resp.text


class _ClaudeAdapter:
    """Wrap ClaudeReviewer so it can sit in the chain (optional third provider)."""
    name = "claude"

    def __init__(self, sop_text, cfg, model=None, api_key=None):
        self.model = model or DEFAULT_MODELS["claude"]
        self._args = (sop_text, cfg, api_key)
        self._inner = None

    def review(self, case):
        if self._inner is None:
            try:
                import anthropic
                sop_text, cfg, key = self._args
                self._inner = ClaudeReviewer(sop_text, cfg, client=anthropic.Anthropic(api_key=key),
                                             model=self.model)
            except Exception as e:
                log.warning("claude unavailable: %s", e)
                return None
        return self._inner.review(case)


class FallbackReviewer:
    """Ask each reviewer in order; the first usable verdict wins."""

    def __init__(self, reviewers: Sequence):
        self.reviewers = list(reviewers)

    def review(self, case: ReviewCase) -> Optional[LLMVerdict]:
        for r in self.reviewers:
            verdict = r.review(case)
            if verdict is not None:
                return verdict
        return None


_FACTORIES = {"openai": OpenAIReviewer, "gemini": GeminiReviewer, "claude": _ClaudeAdapter}


def build_reviewer_chain(names: Sequence[str], sop_text: str, cfg: RulesConfig,
                         env: Optional[Mapping[str, str]] = None):
    """Return (reviewer, human-readable status). Providers without an API key are skipped."""
    env = os.environ if env is None else env
    chain, notes = [], []
    for name in names:
        if name not in _FACTORIES:
            raise ValueError(f"unknown LLM provider {name!r}; choose from {sorted(_FACTORIES)}")
        key = next((env[v] for v in KEY_VARS[name] if env.get(v)), None)
        if not key:
            notes.append(f"{name}: skipped (no API key; set {' or '.join(KEY_VARS[name])})")
            continue
        r = _FACTORIES[name](sop_text, cfg, model=env.get(MODEL_VARS[name]) or None, api_key=key)
        chain.append(r)
        notes.append(f"{name}: {r.model}" + (" (primary)" if len(chain) == 1 else " (fallback)"))
    if not chain:
        return NullReviewer(), "no API key for any provider; code decisions only. " + "; ".join(notes)
    return FallbackReviewer(chain), "; ".join(notes)
