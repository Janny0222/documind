"""AI provider behind a small interface (Phase 1: "design integrations so providers can be replaced").

- GeminiProvider: Google Gen AI SDK. Embeddings (gemini-embedding-001 @768) and streamed answers.
- FakeProvider: deterministic and offline - used by tests and when no API key is configured,
  so the whole app (and CI) runs without network access or quota.

Errors are normalized to AIQuotaError (rate limit / quota exhausted - try later) and
AIUnavailableError (anything else), so callers never depend on SDK exception types.
"""

import hashlib
import math
import re
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Literal, Protocol

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)

EmbedTask = Literal["document", "query"]


class AIError(Exception):
    pass


class AIQuotaError(AIError):
    """Rate limit or quota exhausted. Retrying later may work; never switch to paid usage."""


class AIUnavailableError(AIError):
    pass


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class EmbeddingResult:
    vectors: list[list[float]]
    usage: Usage = field(default_factory=Usage)


@dataclass
class StreamEvent:
    """Either a text delta, or the final event carrying token usage."""

    text: str = ""
    final: bool = False
    usage: Usage | None = None


@dataclass(frozen=True)
class ChatTurn:
    role: Literal["user", "model"]
    text: str


class AIProvider(Protocol):
    name: str
    chat_model: str
    embedding_model_id: str  # e.g. "gemini-embedding-001@768" - stored per chunk
    relevance_floor: float  # cosine similarity below which a passage counts as unrelated

    async def embed(self, texts: Sequence[str], task: EmbedTask) -> EmbeddingResult: ...

    def stream(self, system: str, turns: Sequence[ChatTurn]) -> AsyncIterator[StreamEvent]: ...

    async def complete(self, system: str, prompt: str) -> tuple[str, Usage]: ...


def l2_normalize(vec: Sequence[float]) -> list[float]:
    """Truncated (Matryoshka) Gemini embeddings aren't unit length; normalize for cosine."""
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


# ------------------------------------------------------------------ Gemini


class GeminiProvider:
    name = "gemini"

    def __init__(self) -> None:
        from google import genai

        s = get_settings()
        if s.gemini_api_key is None:
            raise AIUnavailableError("GEMINI_API_KEY is not configured")
        self._client = genai.Client(api_key=s.gemini_api_key.get_secret_value())
        self.chat_model = s.gemini_chat_model
        self.embedding_model = s.gemini_embedding_model
        self.dim = s.embedding_dim
        self.embedding_model_id = f"{self.embedding_model}@{self.dim}"
        self.relevance_floor = s.retrieval_min_similarity

    @staticmethod
    def _translate(exc: Exception) -> AIError:
        from google.genai import errors

        if isinstance(exc, errors.APIError):
            code = getattr(exc, "code", None)
            status = str(getattr(exc, "status", "") or "")
            if code == 429 or "RESOURCE_EXHAUSTED" in status:
                return AIQuotaError("The AI provider's rate limit or quota was reached")
            return AIUnavailableError(f"AI provider error {code}")
        return AIUnavailableError(type(exc).__name__)

    async def embed(self, texts: Sequence[str], task: EmbedTask) -> EmbeddingResult:
        from google.genai import types

        try:
            resp = await self._client.aio.models.embed_content(
                model=self.embedding_model,
                contents=list(texts),
                config=types.EmbedContentConfig(
                    task_type="RETRIEVAL_DOCUMENT" if task == "document" else "RETRIEVAL_QUERY",
                    output_dimensionality=self.dim,
                ),
            )
        except Exception as exc:
            raise self._translate(exc) from exc
        vectors = [l2_normalize(e.values or []) for e in (resp.embeddings or [])]
        if len(vectors) != len(texts) or any(len(v) != self.dim for v in vectors):
            raise AIUnavailableError("Unexpected embedding response shape")
        # Embedding responses may not report tokens; estimate (~4 chars/token) for the usage ledger.
        return EmbeddingResult(vectors, Usage(input_tokens=sum(len(t) for t in texts) // 4))

    def _config(self, system: str):  # type: ignore[no-untyped-def]
        from google.genai import types

        s = get_settings()
        return types.GenerateContentConfig(
            system_instruction=system,
            temperature=s.ai_temperature,
            max_output_tokens=s.ai_max_output_tokens,
        )

    async def stream(self, system: str, turns: Sequence[ChatTurn]) -> AsyncIterator[StreamEvent]:
        from google.genai import types

        contents = [
            types.Content(role=t.role, parts=[types.Part.from_text(text=t.text)]) for t in turns
        ]
        usage = Usage()
        try:
            # google-genai 3.x: an async function returning the async iterator.
            stream = await self._client.aio.models.generate_content_stream(
                model=self.chat_model, contents=contents, config=self._config(system)
            )
            async for chunk in stream:
                if chunk.usage_metadata:
                    usage = Usage(
                        chunk.usage_metadata.prompt_token_count or 0,
                        chunk.usage_metadata.candidates_token_count or 0,
                    )
                if chunk.text:
                    yield StreamEvent(text=chunk.text)
        except AIError:
            raise
        except Exception as exc:
            raise self._translate(exc) from exc
        yield StreamEvent(final=True, usage=usage)

    async def complete(self, system: str, prompt: str) -> tuple[str, Usage]:
        try:
            resp = await self._client.aio.models.generate_content(
                model=self.chat_model, contents=prompt, config=self._config(system)
            )
        except Exception as exc:
            raise self._translate(exc) from exc
        u = resp.usage_metadata
        return (resp.text or "").strip(), Usage(
            (u.prompt_token_count or 0) if u else 0, (u.candidates_token_count or 0) if u else 0
        )


# ------------------------------------------------------------------ Fake (offline, deterministic)

_WORD = re.compile(r"[a-z0-9]+")


class FakeProvider:
    """Bag-of-words hashing embeddings + an extractive "answer" that cites the best source.
    Good enough to exercise retrieval, citations, streaming and limits without any network."""

    name = "fake"
    chat_model = "fake-chat"

    def __init__(self) -> None:
        self.dim = get_settings().embedding_dim
        self.embedding_model_id = f"fake-embedding@{self.dim}"
        self.relevance_floor = 0.45  # bag-of-words vectors have their own scale
        self.fail_with: AIError | None = None  # tests can force an error

    def _vector(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for word in _WORD.findall(text.lower()):
            if len(word) < 3:
                continue
            h = int(hashlib.sha256(word.encode()).hexdigest(), 16)
            vec[h % self.dim] += 1.0
        return l2_normalize(vec) if any(vec) else [1.0 / math.sqrt(self.dim)] * self.dim

    async def embed(self, texts: Sequence[str], task: EmbedTask) -> EmbeddingResult:
        if self.fail_with:
            raise self.fail_with
        return EmbeddingResult(
            [self._vector(t) for t in texts], Usage(sum(len(t) for t in texts) // 4, 0)
        )

    async def stream(self, system: str, turns: Sequence[ChatTurn]) -> AsyncIterator[StreamEvent]:
        if self.fail_with:
            raise self.fail_with
        prompt = turns[-1].text if turns else ""
        sources = re.findall(r'<source id="(S\d+)"[^>]*>\n(.*?)\n</source>', prompt, re.S)
        if not sources:
            answer = "I couldn't find this in the selected documents."
        else:
            sid, text = sources[0]
            first_sentence = re.split(r"(?<=[.!?])\s", text.strip(), maxsplit=1)[0]
            answer = f"According to the documents, {first_sentence} [{sid}]"
        answer += "\n\n---FOLLOW-UPS---\nWhat else does it say?\nWho does this apply to?"
        for i in range(0, len(answer), 12):
            yield StreamEvent(text=answer[i : i + 12])
        yield StreamEvent(final=True, usage=Usage(len(prompt) // 4, len(answer) // 4))

    async def complete(self, system: str, prompt: str) -> tuple[str, Usage]:
        if self.fail_with:
            raise self.fail_with
        last = prompt.strip().splitlines()[-1] if prompt.strip() else ""
        return last.removeprefix("Follow-up question:").strip(), Usage(len(prompt) // 4, 10)


@lru_cache
def get_ai() -> AIProvider:
    s = get_settings()
    if s.ai_provider == "fake":
        return FakeProvider()
    return GeminiProvider()


def ai_configured() -> bool:
    s = get_settings()
    return s.ai_provider == "fake" or s.gemini_api_key is not None
