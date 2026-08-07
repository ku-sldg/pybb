"""
LLM completion backends for the synthesis engines' LlmEngine slot.

SAFETY POLICY (standing, shared with the AutoVerus integration): nothing
here is invoked unless the user armed an engine via an explicit flag
(the examples' --llm {anthropic,openai}); API keys live in environment
variables ONLY — read at call time, never accepted as arguments, stored,
or logged. The Anthropic backend additionally honors an existing
`ant auth login` profile via the SDK's own credential resolution; either
way this module never touches a key value. Factories fail with a clear
message BEFORE any network activity when the backend is unusable.

Each factory returns a `complete(prompt) -> str` callable (empty string
= no candidate, e.g. a safety refusal) with a `.describe()` attribute
for the pre-flight confirmation print and a `.usage` counter the caller
may report after a run (COST POLICY: an armed run reports what it spent;
`DryRunComplete` predicts the ceiling without any network call).
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Callable, Optional

ANTHROPIC_MODEL = "claude-opus-5"
OPENAI_MODEL = "gpt-4o"

# Reasoning-family chat models: `max_completion_tokens` replaces
# `max_tokens`, and the budget is shared with (usually dominated by)
# invisible reasoning tokens — hence the larger default.
_REASONING_PREFIXES = ("gpt-5", "o1", "o3", "o4")
DEFAULT_MAX_TOKENS = 4096
REASONING_MAX_TOKENS = 16384


def _is_reasoning(model: str) -> bool:
    return model.startswith(_REASONING_PREFIXES)


def _default_max_tokens(model: str) -> int:
    return REASONING_MAX_TOKENS if _is_reasoning(model) else DEFAULT_MAX_TOKENS


class LlmBackendError(RuntimeError):
    """The backend cannot run (missing package/credentials) — raised by
    the factory, before any network call."""


class Usage:
    """Per-run token accounting, so an armed run reports what it actually
    spent instead of leaving the cost to be guessed."""

    def __init__(self) -> None:
        self.calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.reasoning_tokens = 0

    def add(self, payload: dict) -> None:
        self.calls += 1
        usage = payload.get("usage") or {}
        self.prompt_tokens += usage.get("prompt_tokens") or usage.get(
            "input_tokens") or 0
        self.completion_tokens += usage.get("completion_tokens") or usage.get(
            "output_tokens") or 0
        details = usage.get("completion_tokens_details") or {}
        self.reasoning_tokens += details.get("reasoning_tokens") or 0

    def report(self) -> str:
        return (f"LLM usage: {self.calls} calls, "
                f"{self.prompt_tokens} input + {self.completion_tokens} output "
                f"tokens (of which {self.reasoning_tokens} reasoning)")


class DryRunComplete:
    """A no-network stand-in for a backend: records every prompt the
    engines would have sent and returns no candidate.

    Because an empty completion is never accepted, the flow walks its
    WORST-CASE path — every attempt on every failing goal — so the call
    count and input-token total it reports are an upper bound on the
    live run, not a sample of it. Output tokens cannot be predicted this
    way and are left to the caller's estimate.
    """

    def __init__(self, model: str, provider: str = "openai") -> None:
        self.model = model
        self.prompts: list = []
        self.describe = (f"provider={provider} model={model} "
                         "DRY RUN — no network calls, no spend")

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return ""

    def report(self) -> str:
        chars = sum(len(p) for p in self.prompts)
        # ~4 chars/token is the standard rough English/code ratio; exact
        # counts are only knowable from the API's own tokenizer
        approx = chars // 4
        largest = max((len(p) for p in self.prompts), default=0)
        return (f"DRY RUN ceiling: {len(self.prompts)} calls, ~{approx} input "
                f"tokens total (~{approx // max(len(self.prompts), 1)} avg, "
                f"~{largest // 4} largest) — worst case, no goal ever solved")


def make_anthropic_complete(model: str = ANTHROPIC_MODEL,
                            max_tokens: int = 4096) -> Callable[[str], str]:
    """
    Claude via the official SDK. Credentials resolve inside the SDK
    (ANTHROPIC_API_KEY, or an `ant auth login` profile) — our code never
    sees the value. Includes the recommended server-side refusal
    fallback; a refusal yields no candidate rather than an error.
    """
    try:
        import anthropic
    except ImportError as e:
        raise LlmBackendError(
            "the 'anthropic' package is not installed in this environment "
            "(pip install anthropic)") from e

    key_source = "ANTHROPIC_API_KEY (env)" if os.environ.get(
        "ANTHROPIC_API_KEY") else "`ant auth login` profile / SDK resolution"
    try:
        client = anthropic.Anthropic()
    except Exception as e:  # no credentials resolvable at construction
        raise LlmBackendError(
            "no Anthropic credentials — set ANTHROPIC_API_KEY or run "
            "`ant auth login`") from e

    def complete(prompt: str) -> str:
        try:
            response = client.beta.messages.create(
                model=model,
                max_tokens=max_tokens,
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                messages=[{"role": "user", "content": prompt}],
            )
        except anthropic.AuthenticationError as e:
            raise LlmBackendError(
                "Anthropic authentication failed — set ANTHROPIC_API_KEY "
                "or run `ant auth login`") from e
        if response.stop_reason == "refusal":
            return ""  # no candidate; the engine simply yields nothing
        return "".join(block.text for block in response.content
                       if block.type == "text")

    complete.describe = (  # type: ignore[attr-defined]
        f"provider=anthropic model={model} max_tokens={max_tokens} "
        f"credentials={key_source}")
    return complete


def make_openai_complete(model: str = OPENAI_MODEL,
                         max_tokens: Optional[int] = None,
                         effort: Optional[str] = None,
                         timeout: int = 600
                         ) -> Callable[[str], str]:
    """
    OpenAI via stdlib HTTP (no dependency). OPENAI_API_KEY is read from
    the environment at call time and travels only in the request header.

    The reasoning families (gpt-5*, o*) take `max_completion_tokens`
    rather than `max_tokens`, and spend most of that budget on invisible
    reasoning tokens — hence the larger default for them. They do NOT
    reason by default on this endpoint (a gpt-5.1 call with no
    `reasoning_effort` reports zero reasoning tokens), so `effort` is
    what actually buys thinking — and what the run pays for.
    """
    if not os.environ.get("OPENAI_API_KEY"):
        raise LlmBackendError(
            "OPENAI_API_KEY is not set — export it in the environment "
            "(never pass keys as arguments)")

    endpoint = "https://api.openai.com/v1/chat/completions"
    budget = max_tokens if max_tokens is not None else _default_max_tokens(model)
    token_param = ("max_completion_tokens" if _is_reasoning(model)
                   else "max_tokens")
    usage = Usage()

    def complete(prompt: str) -> str:
        request_body = {
            "model": model,
            token_param: budget,
            "messages": [{"role": "user", "content": prompt}],
        }
        if effort:
            request_body["reasoning_effort"] = effort
        body = json.dumps(request_body).encode()
        request = urllib.request.Request(
            endpoint, data=body, method="POST",
            headers={
                "Content-Type": "application/json",
                # read at call time; never stored on the closure
                "Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}",
            })
        try:
            with urllib.request.urlopen(request, timeout=timeout) as resp:
                payload = json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:200]
            # transient upstream trouble (rate limit, gateway, outage) is
            # not a run-ending event — yield no candidate and let the
            # engine's next attempt try again. A credential or request
            # error IS terminal: retrying cannot fix it.
            if e.code == 429 or e.code >= 500:
                print(f"  [llm] transient API error {e.code} — no candidate")
                return ""
            raise LlmBackendError(
                f"OpenAI API error {e.code}: {detail}") from e
        except (urllib.error.URLError, ConnectionError) as e:
            print(f"  [llm] connection error ({e}) — no candidate")
            return ""
        except TimeoutError:
            # a slow reasoning call is not a run-ending event: yield no
            # candidate and let the engine's next attempt (or the next
            # rung) proceed, exactly as for a refusal
            print(f"  [llm] no response within {timeout}s — no candidate")
            return ""
        usage.add(payload)
        choices = payload.get("choices") or []
        if not choices:
            return ""
        return (choices[0].get("message") or {}).get("content") or ""

    complete.describe = (  # type: ignore[attr-defined]
        f"provider=openai model={model} {token_param}={budget} "
        f"reasoning_effort={effort or 'unset (no reasoning)'} "
        "credentials=OPENAI_API_KEY (env)")
    complete.usage = usage  # type: ignore[attr-defined]
    return complete


BACKENDS = {
    "anthropic": make_anthropic_complete,
    "openai": make_openai_complete,
}
