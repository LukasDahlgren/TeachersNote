from typing import Callable

ProgressEmitter = Callable[[str, str, int], None]


def emit_progress(
    emit: ProgressEmitter | None,
    stage: str,
    message: str,
    progress_pct: int,
) -> None:
    if emit is None:
        return
    bounded = max(0, min(100, int(progress_pct)))
    emit(stage, message, bounded)
