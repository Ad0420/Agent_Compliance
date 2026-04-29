"""LLM provider abstraction for the simulator.

Mode A (sales demo) → real OpenAI / Anthropic, recorded via Vera's audited
wrappers so every LLM call lands in the audit chain.

Mode B (CI) → CassetteProvider replays prompt-keyed JSON fixtures so tests
are deterministic and free.

The simulator deliberately mixes providers across customers — OpenAI for
ScribeMD's note drafting, Anthropic for orders extraction — so a single
demo run exercises both `AuditedOpenAI` and `AuditedAnthropic`.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class LLMResponse:
    """Provider-neutral response shape."""

    text: str
    input_tokens: int
    output_tokens: int
    model: str
    duration_ms: int


class LLMProvider:
    """Base class. Subclasses implement `chat`."""

    def chat(
        self,
        system: str,
        user: str,
        max_tokens: int = 512,
    ) -> LLMResponse:
        raise NotImplementedError


# ── OpenAI (real) ───────────────────────────────────────────────────────────


class OpenAIProvider(LLMProvider):
    """Real OpenAI calls. Wrapped by Vera's `AuditedOpenAI` upstream when used
    inside an agent so each call records into the audit chain automatically."""

    def __init__(self, model: str = "gpt-4o-mini", audited_client=None):
        if audited_client is None:
            import openai

            self._client = openai.OpenAI()
        else:
            self._client = audited_client
        self.model = model

    def chat(self, system: str, user: str, max_tokens: int = 512) -> LLMResponse:
        t0 = time.time()
        resp = self._client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        elapsed_ms = int((time.time() - t0) * 1000)
        usage = resp.usage
        return LLMResponse(
            text=resp.choices[0].message.content.strip(),
            input_tokens=usage.prompt_tokens,
            output_tokens=usage.completion_tokens,
            model=self.model,
            duration_ms=elapsed_ms,
        )


# ── Anthropic (real) ────────────────────────────────────────────────────────


class AnthropicProvider(LLMProvider):
    """Real Anthropic calls. Wrap with `AuditedAnthropic` upstream for auditing."""

    def __init__(self, model: str = "claude-sonnet-4-6", audited_client=None):
        if audited_client is None:
            import anthropic

            self._client = anthropic.Anthropic()
        else:
            self._client = audited_client
        self.model = model

    def chat(self, system: str, user: str, max_tokens: int = 512) -> LLMResponse:
        t0 = time.time()
        resp = self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        elapsed_ms = int((time.time() - t0) * 1000)
        text_blocks = [
            b.text for b in resp.content if getattr(b, "type", None) == "text"
        ]
        return LLMResponse(
            text="".join(text_blocks).strip(),
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
            model=self.model,
            duration_ms=elapsed_ms,
        )


# ── Cassette (replay for Mode B / CI) ───────────────────────────────────────


class CassetteProvider(LLMProvider):
    """Deterministic replay from a JSON cassette keyed by prompt hash.

    Cassettes live under `simulator/tests/cassettes/<customer>/<workflow>.json`
    and are committed to the repo so CI is hermetic.

    Recording: when no cassette entry exists for a (system, user) pair, the
    provider falls through to a wrapped `real` provider, captures the
    response, and writes the cassette. Set `record=True` in the constructor
    or via env `SIMULATOR_RECORD_CASSETTES=1` to enable recording. By
    default a cache miss is a hard error — CI must be deterministic.
    """

    def __init__(
        self,
        cassette_path: str | Path,
        model: str,
        real_provider: Optional[LLMProvider] = None,
        record: bool = False,
    ):
        self.cassette_path = Path(cassette_path)
        self.model = model
        self.real_provider = real_provider
        self.record = record or os.getenv("SIMULATOR_RECORD_CASSETTES") == "1"
        self._cache: dict[str, dict] = self._load()

    def _load(self) -> dict[str, dict]:
        if self.cassette_path.exists():
            return json.loads(self.cassette_path.read_text())
        return {}

    def _save(self) -> None:
        self.cassette_path.parent.mkdir(parents=True, exist_ok=True)
        self.cassette_path.write_text(json.dumps(self._cache, indent=2, sort_keys=True))

    @staticmethod
    def _key(system: str, user: str, model: str, max_tokens: int) -> str:
        blob = json.dumps(
            {"system": system, "user": user, "model": model, "max_tokens": max_tokens},
            sort_keys=True,
        )
        return hashlib.sha256(blob.encode()).hexdigest()[:16]

    def chat(self, system: str, user: str, max_tokens: int = 512) -> LLMResponse:
        key = self._key(system, user, self.model, max_tokens)
        if key in self._cache:
            entry = self._cache[key]
            return LLMResponse(
                text=entry["text"],
                input_tokens=entry["input_tokens"],
                output_tokens=entry["output_tokens"],
                model=entry["model"],
                duration_ms=entry["duration_ms"],
            )
        if not self.record or self.real_provider is None:
            raise RuntimeError(
                f"Cassette miss for key={key} at {self.cassette_path}. "
                "Set SIMULATOR_RECORD_CASSETTES=1 and provide a real_provider "
                "to record, or update the cassette."
            )
        resp = self.real_provider.chat(system, user, max_tokens=max_tokens)
        self._cache[key] = {
            "text": resp.text,
            "input_tokens": resp.input_tokens,
            "output_tokens": resp.output_tokens,
            "model": resp.model,
            "duration_ms": resp.duration_ms,
            "_recorded_from": {"system": system[:80], "user": user[:80]},
        }
        self._save()
        return resp


# ── Factory ────────────────────────────────────────────────────────────────


def get_provider(
    name: str,
    *,
    mode: str = "A",
    cassette_dir: Optional[Path] = None,
    cassette_name: Optional[str] = None,
) -> LLMProvider:
    """Return a provider for `name` ("openai" | "anthropic"), tuned per mode.

    Mode A → real provider.
    Mode B → CassetteProvider wrapping a real provider for record-on-miss.
    Mode C → real provider (chaos targets Vera, not LLMs).
    """
    name = name.lower()
    if name == "openai":
        real: LLMProvider = OpenAIProvider()
        model = "gpt-4o-mini"
    elif name == "anthropic":
        real = AnthropicProvider()
        model = "claude-sonnet-4-6"
    else:
        raise ValueError(f"Unknown LLM provider: {name!r}")

    if mode == "B":
        if cassette_dir is None or cassette_name is None:
            raise ValueError("Mode B requires cassette_dir and cassette_name")
        return CassetteProvider(
            cassette_path=cassette_dir / f"{cassette_name}.json",
            model=model,
            real_provider=real,
        )
    return real
