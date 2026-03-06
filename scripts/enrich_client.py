import os
from typing import Any, Callable

try:
    import anthropic
except ImportError:  # pragma: no cover - exercised only in minimal local envs
    anthropic = None  # type: ignore[assignment]

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - exercised only in minimal local envs
    OpenAI = None  # type: ignore[assignment]


def _env_truthy(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, *, minimum: int = 1, maximum: int | None = None) -> int:
    raw = os.getenv(name)
    if raw is None:
        parsed = default
    else:
        try:
            parsed = int(raw.strip())
        except ValueError:
            parsed = default
    parsed = max(minimum, parsed)
    if maximum is not None:
        parsed = min(maximum, parsed)
    return parsed


DEFAULT_ENRICH_PROVIDER = os.getenv("ENRICH_PROVIDER", "anthropic").strip().lower() or "anthropic"
DEFAULT_ENRICH_MODEL_OVERRIDE = os.getenv("ENRICH_MODEL", "").strip()
DEFAULT_ENRICH_MODEL_ANTHROPIC = os.getenv("ENRICH_MODEL_ANTHROPIC", "claude-haiku-4-5").strip() or "claude-haiku-4-5"
DEFAULT_ENRICH_MODEL_GROQ = os.getenv("ENRICH_MODEL_GROQ", "openai/gpt-oss-20b").strip() or "openai/gpt-oss-20b"
DEFAULT_ENRICH_MAX_WORKERS = _env_int("ENRICH_MAX_WORKERS", 1, minimum=1)
DEFAULT_ENRICH_MAX_TRANSCRIPT_WORDS = _env_int("ENRICH_MAX_TRANSCRIPT_WORDS", 700, minimum=1)
DEFAULT_ENRICH_MAX_OUTPUT_TOKENS = _env_int("ENRICH_MAX_OUTPUT_TOKENS", 320, minimum=64)
DEFAULT_ENRICH_MAX_ATTEMPTS = _env_int("ENRICH_MAX_ATTEMPTS", 4, minimum=1)
DEFAULT_ENRICH_BATCH_SIZE = _env_int("ENRICH_BATCH_SIZE", 1, minimum=1, maximum=8)
DEFAULT_ENRICH_LOG_USAGE = _env_truthy("ENRICH_LOG_USAGE", True)

SUPPORTED_ENRICH_PROVIDERS = {"anthropic", "groq"}


def resolve_enrichment_provider(provider: str | None = None) -> str:
    candidate = (provider or DEFAULT_ENRICH_PROVIDER).strip().lower()
    if candidate not in SUPPORTED_ENRICH_PROVIDERS:
        supported = ", ".join(sorted(SUPPORTED_ENRICH_PROVIDERS))
        raise ValueError(f"Unsupported ENRICH_PROVIDER={candidate!r}. Supported: {supported}")
    return candidate


def default_enrichment_model(provider: str) -> str:
    if provider == "anthropic":
        return DEFAULT_ENRICH_MODEL_ANTHROPIC
    return DEFAULT_ENRICH_MODEL_GROQ


def create_enrichment_client(provider: str | None = None) -> Any:
    resolved = resolve_enrichment_provider(provider)
    if resolved == "anthropic":
        if anthropic is None:
            raise RuntimeError("anthropic package is required for ENRICH_PROVIDER=anthropic")
        return anthropic.Anthropic()

    if OpenAI is None:
        raise RuntimeError("openai package is required for ENRICH_PROVIDER=groq")
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is required for ENRICH_PROVIDER=groq")
    return OpenAI(api_key=api_key, base_url="https://api.groq.com/openai/v1")


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _usage_from_response(response: Any, provider: str) -> dict[str, int]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

    if provider == "anthropic":
        input_tokens = _safe_int(getattr(usage, "input_tokens", 0))
        output_tokens = _safe_int(getattr(usage, "output_tokens", 0))
    else:
        input_tokens = _safe_int(getattr(usage, "prompt_tokens", 0))
        output_tokens = _safe_int(getattr(usage, "completion_tokens", 0))

    total_tokens = _safe_int(getattr(usage, "total_tokens", input_tokens + output_tokens))
    if total_tokens == 0:
        total_tokens = input_tokens + output_tokens
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


def _is_rate_limit_error(exc: Exception) -> bool:
    if anthropic is not None:
        overloaded = getattr(anthropic, "OverloadedError", None)
        types = (anthropic.RateLimitError,) + ((overloaded,) if overloaded else ())
        if isinstance(exc, types):
            return True
    name = exc.__class__.__name__.lower()
    return name in ("ratelimiterror", "overloadederror")


def _is_connection_error(exc: Exception) -> bool:
    name = exc.__class__.__name__.lower()
    if "connection" in name or "timeout" in name:
        return True
    message = str(exc).lower()
    return "connection error" in message or "timeout" in message


def _add_usage(acc: dict[str, int], usage: dict[str, int]) -> None:
    acc["input_tokens"] += _safe_int(usage.get("input_tokens"))
    acc["output_tokens"] += _safe_int(usage.get("output_tokens"))
    acc["total_tokens"] += _safe_int(usage.get("total_tokens"))


def _response_text_from_groq_completion(response: Any) -> str:
    choices = getattr(response, "choices", None) or []
    if not choices:
        return ""
    message = getattr(choices[0], "message", None)
    content = getattr(message, "content", "") if message is not None else ""
    if isinstance(content, list):
        parts = []
        for part in content:
            text = part.get("text") if isinstance(part, dict) else None
            if text:
                parts.append(str(text))
        return "\n".join(parts).strip()
    if content is None:
        return ""
    return str(content).strip()


def _call_enrichment_model(
    client: Any,
    *,
    provider: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    max_output_tokens: int,
    token_callback: Callable[[str], None] | None = None,
) -> tuple[str, dict[str, int]]:
    if provider == "anthropic":
        accumulated = ""
        with client.messages.stream(
            model=model,
            max_tokens=max_output_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        ) as stream:
            for text in stream.text_stream:
                accumulated += text
                if token_callback:
                    token_callback(text)
            response = stream.get_final_message()
        return accumulated.strip(), _usage_from_response(response, provider)

    accumulated = ""
    final_chunk = None
    stream = client.chat.completions.create(
        model=model,
        temperature=0,
        max_tokens=max_output_tokens,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        extra_body={"thinking": {"type": "disabled"}},
        stream=True,
        stream_options={"include_usage": True},
    )
    for chunk in stream:
        delta = chunk.choices[0].delta.content or ""
        accumulated += delta
        if token_callback and delta:
            token_callback(delta)
        final_chunk = chunk
    raw = accumulated.strip()
    usage = _usage_from_response(final_chunk, provider) if final_chunk is not None else {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    return raw, usage
