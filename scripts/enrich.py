import argparse
import time
from typing import Any, Callable

try:
    from . import enrich_client as _client
    from . import enrich_parsing as _parsing
    from . import enrich_policy as _policy
    from . import enrich_prompt as _prompt
    from . import enrich_retry as _retry
except ImportError:  # pragma: no cover - direct script execution fallback
    import enrich_client as _client
    import enrich_parsing as _parsing
    import enrich_policy as _policy
    import enrich_prompt as _prompt
    import enrich_retry as _retry

anthropic = _client.anthropic
OpenAI = _client.OpenAI

DEFAULT_ENRICH_PROVIDER = _client.DEFAULT_ENRICH_PROVIDER
DEFAULT_ENRICH_MODEL_OVERRIDE = _client.DEFAULT_ENRICH_MODEL_OVERRIDE
DEFAULT_ENRICH_MODEL_ANTHROPIC = _client.DEFAULT_ENRICH_MODEL_ANTHROPIC
DEFAULT_ENRICH_MODEL_GROQ = _client.DEFAULT_ENRICH_MODEL_GROQ
DEFAULT_ENRICH_MAX_WORKERS = _client.DEFAULT_ENRICH_MAX_WORKERS
DEFAULT_ENRICH_MAX_TRANSCRIPT_WORDS = _client.DEFAULT_ENRICH_MAX_TRANSCRIPT_WORDS
DEFAULT_ENRICH_MAX_OUTPUT_TOKENS = _client.DEFAULT_ENRICH_MAX_OUTPUT_TOKENS
DEFAULT_ENRICH_MAX_ATTEMPTS = _client.DEFAULT_ENRICH_MAX_ATTEMPTS
DEFAULT_ENRICH_BATCH_SIZE = _client.DEFAULT_ENRICH_BATCH_SIZE
DEFAULT_ENRICH_LOG_USAGE = _client.DEFAULT_ENRICH_LOG_USAGE
SUPPORTED_ENRICH_PROVIDERS = _client.SUPPORTED_ENRICH_PROVIDERS

SYSTEM_PROMPT = _prompt.SYSTEM_PROMPT
STRICT_SYSTEM_PROMPT = _prompt.STRICT_SYSTEM_PROMPT
BATCH_SYSTEM_PROMPT = _prompt.BATCH_SYSTEM_PROMPT
STRICT_BATCH_SYSTEM_PROMPT = _prompt.STRICT_BATCH_SYSTEM_PROMPT

KEY_ALIASES = _parsing.KEY_ALIASES
BULLET_PREFIX_RE = _parsing.BULLET_PREFIX_RE
MARKDOWN_BOLD_RE = _parsing.MARKDOWN_BOLD_RE

TOKEN_RE = _policy.TOKEN_RE
OPERATIONAL_CHATTER_KEYWORDS = _policy.OPERATIONAL_CHATTER_KEYWORDS
ACADEMIC_MISC_KEYWORDS = _policy.ACADEMIC_MISC_KEYWORDS
RELEVANCE_STOPWORDS = _policy.RELEVANCE_STOPWORDS
MAX_MISC_ACADEMIC_BULLETS = _policy.MAX_MISC_ACADEMIC_BULLETS
MAX_LECTURER_ADDITIONS_BULLETS = _policy.MAX_LECTURER_ADDITIONS_BULLETS
MIN_SLIDE_CONTENT_BULLETS = _policy.MIN_SLIDE_CONTENT_BULLETS
MAX_SLIDE_CONTENT_BULLETS = _policy.MAX_SLIDE_CONTENT_BULLETS
MIN_KEY_TAKEAWAYS = _policy.MIN_KEY_TAKEAWAYS
MAX_KEY_TAKEAWAYS = _policy.MAX_KEY_TAKEAWAYS
MIN_BULLET_WORDS = _policy.MIN_BULLET_WORDS
TARGET_MIN_DEPTH_RATIO = _policy.TARGET_MIN_DEPTH_RATIO
MIN_NOTE_WORD_FLOOR = _policy.MIN_NOTE_WORD_FLOOR
MAX_NOTE_WORD_FLOOR = _policy.MAX_NOTE_WORD_FLOOR
SUMMARY_MIN_WORDS = _policy.SUMMARY_MIN_WORDS

EnrichmentResponseError = _retry.EnrichmentResponseError

truncate_transcript_for_prompt = _prompt.truncate_transcript_for_prompt
build_user_prompt = _prompt.build_user_prompt
build_batch_user_prompt = _prompt.build_batch_user_prompt

parse_enrichment_response = _parsing.parse_enrichment_response
parse_enrichment_batch_response = _parsing.parse_enrichment_batch_response
normalize_enriched_payload = _parsing.normalize_enriched_payload
is_enriched_payload_invalid = _parsing.is_enriched_payload_invalid

enforce_relevance_policy = _policy.enforce_relevance_policy
build_fallback_enrichment = _retry.build_fallback_enrichment

_collapse_whitespace = _parsing._collapse_whitespace
_string_value = _parsing._string_value
_normalize_takeaways = _parsing._normalize_takeaways
_extract_prefixed_bullets = _parsing._extract_prefixed_bullets
_should_merge_wrapped_line = _parsing._should_merge_wrapped_line
_merge_wrapped_lines = _parsing._merge_wrapped_lines
_normalize_slide_text = _parsing._normalize_slide_text
_split_text_to_bullets = _parsing._split_text_to_bullets
_format_lecturer_additions = _parsing._format_lecturer_additions
_pick_first = _parsing._pick_first
_extract_first_json_block = _parsing._extract_first_json_block
_extract_first_json_object = _parsing._extract_first_json_object
_extract_first_json_array = _parsing._extract_first_json_array
_json_to_dict = _parsing._json_to_dict
_json_to_list_of_dicts = _parsing._json_to_list_of_dicts
_strip_reasoning_blocks = _parsing._strip_reasoning_blocks
_iter_fenced_json_candidates = _parsing._iter_fenced_json_candidates
_sentence_chunks = _parsing._sentence_chunks

_dedupe_keep_order = _policy._dedupe_keep_order
_tokenize_for_relevance = _policy._tokenize_for_relevance
_contains_keyword = _policy._contains_keyword
_is_operational_chatter = _policy._is_operational_chatter
_is_academic_misc_context = _policy._is_academic_misc_context
_word_count = _policy._word_count
_normalize_for_duplicate_check = _policy._normalize_for_duplicate_check
_slide_text_fragments = _policy._slide_text_fragments
_to_summary_sentence = _policy._to_summary_sentence
_candidate_source_priority = _policy._candidate_source_priority
_classify_relevance_tier = _policy._classify_relevance_tier
_make_candidate = _policy._make_candidate
_candidate_sort_key = _policy._candidate_sort_key
_candidate_words = _policy._candidate_words
_depth_word_count = _policy._depth_word_count
_clean_lines_for_relevance = _policy._clean_lines_for_relevance
_format_bullets = _policy._format_bullets

_env_truthy = _client._env_truthy
_env_int = _client._env_int
_safe_int = _client._safe_int
_usage_from_response = _client._usage_from_response
_is_rate_limit_error = _client._is_rate_limit_error
_is_connection_error = _client._is_connection_error
_add_usage = _client._add_usage
_response_text_from_groq_completion = _client._response_text_from_groq_completion

_coerce_slide_number = _retry._coerce_slide_number
_batch_slide_label = _retry._batch_slide_label
_empty_failure_reason_counts = _retry._empty_failure_reason_counts
_record_fallback_reason = _retry._record_fallback_reason
_HEARTBEAT_INTERVAL = _retry._HEARTBEAT_INTERVAL
_sleep_with_heartbeat = _retry._sleep_with_heartbeat


def _sync_client_runtime() -> None:
    _client.anthropic = anthropic
    _client.OpenAI = OpenAI


def resolve_enrichment_provider(provider: str | None = None) -> str:
    _sync_client_runtime()
    return _client.resolve_enrichment_provider(provider)


def default_enrichment_model(provider: str) -> str:
    return _client.default_enrichment_model(provider)


def create_enrichment_client(provider: str | None = None) -> Any:
    _sync_client_runtime()
    return _client.create_enrichment_client(provider)


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
    _sync_client_runtime()
    return _client._call_enrichment_model(
        client,
        provider=provider,
        model=model,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        max_output_tokens=max_output_tokens,
        token_callback=token_callback,
    )


def enrich_slide(
    client: Any,
    slide: dict,
    transcript_text: str,
    provider: str,
    model: str,
    max_output_tokens: int,
    system_prompt: str = SYSTEM_PROMPT,
    token_callback: Callable[[str], None] | None = None,
    course_context: str | None = None,
) -> tuple[dict, dict[str, int]]:
    return _retry.enrich_slide_impl(
        client,
        slide,
        transcript_text,
        provider,
        model,
        max_output_tokens,
        call_enrichment_model_fn=_call_enrichment_model,
        system_prompt=system_prompt,
        token_callback=token_callback,
        course_context=course_context,
    )


def enrich_slides_batch(
    client: Any,
    slides_with_transcripts: list[tuple[dict, str]],
    *,
    provider: str,
    model: str,
    max_output_tokens: int,
    system_prompt: str = BATCH_SYSTEM_PROMPT,
    token_callback: Callable[[str], None] | None = None,
    course_context: str | None = None,
) -> tuple[dict[int, dict], list[tuple[dict, str]], dict[str, int]]:
    return _retry.enrich_slides_batch_impl(
        client,
        slides_with_transcripts,
        provider=provider,
        model=model,
        max_output_tokens=max_output_tokens,
        call_enrichment_model_fn=_call_enrichment_model,
        system_prompt=system_prompt,
        token_callback=token_callback,
        course_context=course_context,
    )


def enrich_slide_with_retry(
    client: Any,
    slide: dict,
    transcript_text: str,
    *,
    provider: str,
    model: str,
    max_output_tokens: int = DEFAULT_ENRICH_MAX_OUTPUT_TOKENS,
    max_transcript_words: int = DEFAULT_ENRICH_MAX_TRANSCRIPT_WORDS,
    max_attempts: int = DEFAULT_ENRICH_MAX_ATTEMPTS,
    log_usage: bool = DEFAULT_ENRICH_LOG_USAGE,
    log_callback: Callable[[str], None] | None = None,
    token_callback: Callable[[str], None] | None = None,
    course_context: str | None = None,
) -> tuple[dict, dict[str, Any]]:
    return _retry.enrich_slide_with_retry_impl(
        client,
        slide,
        transcript_text,
        provider=provider,
        model=model,
        call_enrichment_model_fn=_call_enrichment_model,
        max_output_tokens=max_output_tokens,
        max_transcript_words=max_transcript_words,
        max_attempts=max_attempts,
        log_usage=log_usage,
        log_callback=log_callback,
        token_callback=token_callback,
        course_context=course_context,
    )


def enrich_slides_batch_with_retry(
    client: Any,
    slides_with_transcripts: list[tuple[dict, str]],
    *,
    provider: str,
    model: str,
    max_output_tokens: int = DEFAULT_ENRICH_MAX_OUTPUT_TOKENS,
    max_transcript_words: int = DEFAULT_ENRICH_MAX_TRANSCRIPT_WORDS,
    max_attempts: int = DEFAULT_ENRICH_MAX_ATTEMPTS,
    log_usage: bool = DEFAULT_ENRICH_LOG_USAGE,
    log_callback: Callable[[str], None] | None = None,
    token_callback: Callable[[str], None] | None = None,
    course_context: str | None = None,
) -> tuple[list[dict], dict[str, Any]]:
    return _retry.enrich_slides_batch_with_retry_impl(
        client,
        slides_with_transcripts,
        provider=provider,
        model=model,
        call_enrichment_model_fn=_call_enrichment_model,
        enrich_slide_with_retry_fn=enrich_slide_with_retry,
        max_output_tokens=max_output_tokens,
        max_transcript_words=max_transcript_words,
        max_attempts=max_attempts,
        log_usage=log_usage,
        log_callback=log_callback,
        token_callback=token_callback,
        course_context=course_context,
    )


def enrich(
    slides_path: str,
    aligned_path: str,
    transcript_path: str,
    output_path: str,
    max_workers: int = DEFAULT_ENRICH_MAX_WORKERS,
    max_attempts: int = DEFAULT_ENRICH_MAX_ATTEMPTS,
    max_transcript_words: int = DEFAULT_ENRICH_MAX_TRANSCRIPT_WORDS,
    max_output_tokens: int = DEFAULT_ENRICH_MAX_OUTPUT_TOKENS,
    provider: str | None = None,
    model: str | None = None,
    log_usage: bool = DEFAULT_ENRICH_LOG_USAGE,
) -> None:
    return _retry.enrich_impl(
        slides_path,
        aligned_path,
        transcript_path,
        output_path,
        resolve_enrichment_provider_fn=resolve_enrichment_provider,
        default_enrichment_model_fn=default_enrichment_model,
        create_enrichment_client_fn=create_enrichment_client,
        enrich_slides_batch_with_retry_fn=enrich_slides_batch_with_retry,
        default_enrich_model_override=DEFAULT_ENRICH_MODEL_OVERRIDE,
        default_enrich_batch_size=DEFAULT_ENRICH_BATCH_SIZE,
        max_workers=max_workers,
        max_attempts=max_attempts,
        max_transcript_words=max_transcript_words,
        max_output_tokens=max_output_tokens,
        provider=provider,
        model=model,
        log_usage=log_usage,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Enrich slides with lecturer transcript using AI")
    parser.add_argument("--slides", required=True)
    parser.add_argument("--aligned", required=True)
    parser.add_argument("--transcript", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_ENRICH_MAX_WORKERS,
        help=f"Parallel API workers (default {DEFAULT_ENRICH_MAX_WORKERS})",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=DEFAULT_ENRICH_MAX_ATTEMPTS,
        help=f"Retry attempts per slide (default {DEFAULT_ENRICH_MAX_ATTEMPTS})",
    )
    parser.add_argument(
        "--max-transcript-words",
        type=int,
        default=DEFAULT_ENRICH_MAX_TRANSCRIPT_WORDS,
        help=f"Max transcript words in enrichment prompt (default {DEFAULT_ENRICH_MAX_TRANSCRIPT_WORDS})",
    )
    parser.add_argument(
        "--max-output-tokens",
        type=int,
        default=DEFAULT_ENRICH_MAX_OUTPUT_TOKENS,
        help=f"Max completion tokens per enrichment call (default {DEFAULT_ENRICH_MAX_OUTPUT_TOKENS})",
    )
    parser.add_argument(
        "--provider",
        choices=sorted(SUPPORTED_ENRICH_PROVIDERS),
        default=DEFAULT_ENRICH_PROVIDER,
        help=f"LLM provider for enrichment (default {DEFAULT_ENRICH_PROVIDER})",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_ENRICH_MODEL_OVERRIDE,
        help="Override model id for enrichment provider (default uses ENRICH_MODEL / ENRICH_MODEL_* env vars)",
    )
    parser.add_argument(
        "--log-usage",
        action="store_true",
        default=DEFAULT_ENRICH_LOG_USAGE,
        help="Log per-slide usage metrics (default follows ENRICH_LOG_USAGE)",
    )
    parser.add_argument(
        "--no-log-usage",
        action="store_false",
        dest="log_usage",
        help="Disable per-slide usage logging",
    )
    args = parser.parse_args()
    enrich(
        args.slides,
        args.aligned,
        args.transcript,
        args.output,
        max_workers=args.workers,
        max_attempts=args.max_attempts,
        max_transcript_words=args.max_transcript_words,
        max_output_tokens=args.max_output_tokens,
        provider=args.provider,
        model=args.model,
        log_usage=args.log_usage,
    )
