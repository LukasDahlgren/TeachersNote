ALIGNMENT_MODEL_BY_ALIAS = {
    "sonnet": "claude-sonnet-4-6",
    "haiku": "claude-haiku-4-5",
}
DEFAULT_ALIGNMENT_MODEL_ALIAS = "sonnet"


def resolve_alignment_model_alias(raw: str | None) -> str:
    alias = (raw or "").strip().lower()
    if not alias:
        return DEFAULT_ALIGNMENT_MODEL_ALIAS

    if alias not in ALIGNMENT_MODEL_BY_ALIAS:
        allowed = ", ".join(sorted(ALIGNMENT_MODEL_BY_ALIAS))
        raise ValueError(
            f"Invalid ALIGN_MODEL value '{raw}'. Allowed values: {allowed}."
        )
    return alias


def resolve_alignment_model(raw: str | None) -> str:
    alias = resolve_alignment_model_alias(raw)
    return ALIGNMENT_MODEL_BY_ALIAS[alias]
