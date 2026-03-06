"""Lecture chatbot: answers student questions using full lecture context."""

import os
import socket
from typing import Any

try:
    import httpx as _httpx
except ImportError:
    _httpx = None  # type: ignore[assignment]

try:
    import anthropic as _anthropic
except ImportError:
    _anthropic = None  # type: ignore[assignment]

try:
    from openai import OpenAI as _OpenAI
except ImportError:
    _OpenAI = None  # type: ignore[assignment]

try:
    from openai import APIConnectionError as _OpenAIAPIConnectionError
except ImportError:
    _OpenAIAPIConnectionError = None  # type: ignore[assignment]

try:
    from openai import APITimeoutError as _OpenAIAPITimeoutError
except ImportError:
    _OpenAIAPITimeoutError = None  # type: ignore[assignment]

try:
    from anthropic import APIConnectionError as _AnthropicAPIConnectionError
except ImportError:
    _AnthropicAPIConnectionError = None  # type: ignore[assignment]

try:
    from anthropic import APITimeoutError as _AnthropicAPITimeoutError
except ImportError:
    _AnthropicAPITimeoutError = None  # type: ignore[assignment]

CHAT_PROVIDER = os.getenv("CHAT_PROVIDER", "groq").strip().lower() or "groq"
CHAT_MODEL_GROQ = os.getenv("CHAT_MODEL", "llama-3.3-70b-versatile").strip() or "llama-3.3-70b-versatile"
CHAT_MODEL_ANTHROPIC = os.getenv("CHAT_MODEL", "claude-haiku-4-5").strip() or "claude-haiku-4-5"
CHAT_MAX_TOKENS: int = int(os.getenv("CHAT_MAX_TOKENS", "1024") or "1024")
DISABLE_EXTERNAL_AI: bool = os.getenv("DISABLE_EXTERNAL_AI", "").strip().lower() in {"1", "true", "yes", "on"}

SYSTEM_PROMPT = """You are a study assistant for a university lecture notes platform.
You will be given the full lecture content as raw slide text and transcript, organized by slide.
Rules you must follow:
- Answer ONLY from the provided lecture content. Do not infer, guess, or add knowledge not present in the slides or transcript.
- For every substantive claim, cite the supporting slide inline using the format [Slide N].
- If the student asks something that is not supported by the lecture material, reply with a short statement that it is not covered, for example: "det framgår inte av materialet" (or the equivalent in the question's language).
- Do not guess or infer the lecture theme from vague patterns. Only describe what is explicitly stated.
- Detect the language of the student's question and respond in the same language.
- Keep responses focused and educational — around 2-5 sentences unless more detail is clearly needed."""

_MAX_TRANSCRIPT_WORDS_PER_SLIDE = 300

_DNS_ERROR_TOKENS = (
    "name or service not known",
    "temporary failure in name resolution",
    "nodename nor servname provided",
    "failed to resolve",
    "unknown host",
)


class ChatServiceUnavailableError(RuntimeError):
    """Raised when the configured chat provider cannot be reached."""


def _iter_exception_chain(exc: BaseException) -> list[BaseException]:
    chain: list[BaseException] = []
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        chain.append(current)
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return chain


def _format_provider_connectivity_error(provider_name: str, exc: BaseException) -> str | None:
    chain = _iter_exception_chain(exc)
    lowered_messages = " | ".join(str(item).lower() for item in chain if str(item))

    if any(isinstance(item, socket.gaierror) for item in chain) or any(
        token in lowered_messages for token in _DNS_ERROR_TOKENS
    ):
        return (
            f"{provider_name} chat is unavailable because DNS lookup failed. "
            "Check internet connectivity and DNS settings for the host and backend container."
        )

    if any(
        isinstance(
            item,
            tuple(
                cls
                for cls in (
                    _httpx.TimeoutException if _httpx is not None else None,
                    _OpenAIAPITimeoutError,
                    _AnthropicAPITimeoutError,
                )
                if cls is not None
            ),
        )
        for item in chain
    ):
        return (
            f"{provider_name} chat timed out. "
            "Check internet connectivity from the backend container and retry."
        )

    if any(
        isinstance(
            item,
            tuple(
                cls
                for cls in (
                    _httpx.ConnectError if _httpx is not None else None,
                    _OpenAIAPIConnectionError,
                    _AnthropicAPIConnectionError,
                )
                if cls is not None
            ),
        )
        for item in chain
    ):
        return (
            f"{provider_name} chat is unavailable because the provider could not be reached. "
            "Check internet connectivity from the backend container and retry."
        )

    return None


def _reraise_if_provider_unreachable(provider_name: str, exc: BaseException) -> None:
    detail = _format_provider_connectivity_error(provider_name, exc)
    if detail is not None:
        raise ChatServiceUnavailableError(detail) from exc


def build_lecture_context(
    slides: list[dict],
    transcript: list[dict] | None = None,
    alignment: list[dict] | None = None,
) -> str:
    """Format raw slide text + aligned transcript into a context string."""
    # Build a map: slide_number -> list of transcript segment texts
    transcript_by_slide: dict[int, list[str]] = {}
    if transcript and alignment:
        segs = {i: seg["text"] for i, seg in enumerate(transcript)}
        for a in alignment:
            slide_num = int(a["slide"])
            start = int(a["start_segment"])
            end = int(a["end_segment"])
            texts = [segs[i] for i in range(start, end + 1) if i in segs]
            transcript_by_slide[slide_num] = texts

    parts: list[str] = []
    for slide in slides:
        num = slide.get("slide", "?")
        slide_text = slide.get("text", "").strip()

        lines = [f"--- Slide {num} ---"]
        if slide_text:
            lines.append(f"Slide text: {slide_text}")

        # Append actual transcript for this slide (word-capped)
        raw_texts = transcript_by_slide.get(int(num) if str(num).isdigit() else 0, [])
        if raw_texts:
            raw = " ".join(raw_texts)
            words = raw.split()
            if len(words) > _MAX_TRANSCRIPT_WORDS_PER_SLIDE:
                raw = " ".join(words[:_MAX_TRANSCRIPT_WORDS_PER_SLIDE]) + "…"
            lines.append(f"Transcript: {raw}")

        parts.append("\n".join(lines))

    return "\n\n".join(parts)


def chat(
    lecture_context: str,
    history: list[dict[str, str]],
    message: str,
    selected_text: str | None = None,
) -> str:
    """Send a chat message and return the assistant reply."""
    if DISABLE_EXTERNAL_AI:
        return "AI chat is disabled in this environment."

    user_content = message
    if selected_text:
        user_content = f'Regarding this text: "{selected_text}"\n\n{message}'

    system = f"{SYSTEM_PROMPT}\n\n<lecture_notes>\n{lecture_context}\n</lecture_notes>"
    messages: list[dict[str, Any]] = [
        *[{"role": m["role"], "content": m["content"]} for m in history],
        {"role": "user", "content": user_content},
    ]

    if CHAT_PROVIDER == "groq":
        return _chat_groq(system, messages)
    return _chat_anthropic(system, messages)


def _chat_groq(system: str, messages: list[dict[str, Any]]) -> str:
    if _OpenAI is None:
        raise RuntimeError("openai package is required for CHAT_PROVIDER=groq")
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is required for CHAT_PROVIDER=groq")
    client = _OpenAI(api_key=api_key, base_url="https://api.groq.com/openai/v1")
    try:
        response = client.chat.completions.create(
            model=CHAT_MODEL_GROQ,
            messages=[{"role": "system", "content": system}, *messages],  # type: ignore[arg-type]
            max_tokens=CHAT_MAX_TOKENS,
        )
    except Exception as exc:
        _reraise_if_provider_unreachable("Groq", exc)
        raise
    return response.choices[0].message.content or ""


def _chat_anthropic(system: str, messages: list[dict[str, Any]]) -> str:
    if _anthropic is None:
        raise RuntimeError("anthropic package is required for CHAT_PROVIDER=anthropic")
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is required for CHAT_PROVIDER=anthropic")
    client = _anthropic.Anthropic(api_key=api_key)
    try:
        response = client.messages.create(
            model=CHAT_MODEL_ANTHROPIC,
            system=system,
            messages=messages,  # type: ignore[arg-type]
            max_tokens=CHAT_MAX_TOKENS,
        )
    except Exception as exc:
        _reraise_if_provider_unreachable("Anthropic", exc)
        raise
    block = response.content[0] if response.content else None
    return block.text if block and hasattr(block, "text") else ""
