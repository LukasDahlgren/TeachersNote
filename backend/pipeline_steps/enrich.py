import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

try:
    from pipeline_steps.progress import ProgressEmitter
except ImportError:  # pragma: no cover - package import fallback
    from backend.pipeline_steps.progress import ProgressEmitter


def enrich_aligned_slides(
    slides: list[dict],
    transcript: list[dict],
    alignment: list[dict],
    *,
    emit: ProgressEmitter | None,
    on_slide_enriched: Callable[[int, dict], None] | None,
    course_context: str | None,
    emit_progress: Callable[[ProgressEmitter | None, str, str, int], None],
    enrich_slides_batch_notes: Callable[..., tuple[list[dict], dict] | list[dict]],
    build_fallback_enrichment: Callable[[dict, str], dict],
    global_enrich_semaphore: threading.Semaphore,
    enrich_provider: str,
    enrich_model: str,
    enrich_batch_size: int,
    enrich_max_workers: int,
    enrich_max_attempts: int,
    enrich_max_output_tokens: int,
    enrich_max_transcript_words: int,
) -> list[dict]:
    total = len(alignment)
    done_count = 0
    done_lock = threading.Lock()
    metrics_lock = threading.Lock()
    stage_started = time.perf_counter()
    usage_totals = {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "retries": 0,
        "fallbacks": 0,
        "duration_ms": 0,
    }
    failure_reason_counts = {
        "truncated_json": 0,
        "empty_payload": 0,
        "connection_error": 0,
        "other_error": 0,
    }

    print(
        f"✨ Enriching {total} slides via {enrich_provider}:{enrich_model} "
        f"(workers={enrich_max_workers}, retries={enrich_max_attempts}, "
        f"batch_size={enrich_batch_size}, max_output_tokens={enrich_max_output_tokens}, "
        f"max_transcript_words={enrich_max_transcript_words})...",
        flush=True,
    )
    emit_progress(emit, "enrich", f"✨ Enriching {total} slides...", 70)
    slides_by_num = {slide["slide"]: slide for slide in slides}

    def chunk_alignment_rows(rows: list[dict], size: int) -> list[list[dict]]:
        return [rows[idx:idx + size] for idx in range(0, len(rows), size)]

    def enrich_batch(batch: list[dict]) -> list[dict]:
        nonlocal done_count
        batch_inputs: list[tuple[dict, str]] = []
        slide_numbers: list[int] = []
        for row in batch:
            slide = slides_by_num[row["slide"]]
            text = " ".join(
                seg["text"].strip()
                for seg in transcript[row["start_segment"]: row["end_segment"] + 1]
            )
            batch_inputs.append((slide, text))
            slide_numbers.append(int(row["slide"]))
        with done_lock:
            in_progress_done = done_count
        pct_start = 70 + int((in_progress_done / total) * 20) if total > 0 else 70
        if len(slide_numbers) == 1:
            batch_label = str(slide_numbers[0])
        else:
            batch_label = f"{slide_numbers[0]}-{slide_numbers[-1]}"
        print(
            f"  ⏳ Enriching slides {batch_label} ({in_progress_done + 1}/{total})...",
            flush=True,
        )

        def slide_log(message: str) -> None:
            emit_progress(emit, "enrich", message, pct_start)

        with global_enrich_semaphore:
            enriched_batch, metrics = enrich_slides_batch_notes(
                batch_inputs,
                max_attempts=enrich_max_attempts,
                log_callback=slide_log,
                token_callback=slide_log,
                return_metrics=True,
                course_context=course_context,
            )
        with metrics_lock:
            usage_totals["input_tokens"] += int(metrics.get("input_tokens", 0))
            usage_totals["output_tokens"] += int(metrics.get("output_tokens", 0))
            usage_totals["total_tokens"] += int(metrics.get("total_tokens", 0))
            usage_totals["retries"] += int(metrics.get("retries", 0))
            usage_totals["duration_ms"] += int(metrics.get("duration_ms", 0))
            usage_totals["fallbacks"] += int(metrics.get("fallbacks", 0))
            for reason, count in dict(metrics.get("failure_reason_counts", {})).items():
                if reason not in failure_reason_counts:
                    continue
                failure_reason_counts[reason] += int(count)

        enriched_by_slide = {int(entry["slide"]): entry for entry in enriched_batch}
        transcript_by_slide = {
            int(slide["slide"]): text
            for slide, text in batch_inputs
        }
        batch_results: list[dict] = []
        for row in batch:
            slide = slides_by_num[row["slide"]]
            enriched = enriched_by_slide.get(int(row["slide"]))
            if enriched is None:
                enriched = {
                    "slide": row["slide"],
                    **build_fallback_enrichment(slide, transcript_by_slide.get(int(row["slide"]), "")),
                }
            with done_lock:
                done_count += 1
                local_done = done_count
            print(f"  ✅ Slide {row['slide']} done ({local_done}/{total})", flush=True)
            pct = 70 + int((local_done / total) * 20) if total > 0 else 90
            emit_progress(
                emit,
                "enrich",
                f"✅ Slide {row['slide']} done ({local_done}/{total})",
                pct,
            )
            result = {
                "slide": row["slide"],
                "original_text": slide["text"],
                "start_segment": row["start_segment"],
                "end_segment": row["end_segment"],
                "summary": enriched.get("summary", ""),
                "slide_content": enriched.get("slide_content", ""),
                "lecturer_additions": enriched.get("lecturer_additions", ""),
                "key_takeaways": enriched.get("key_takeaways", []),
            }
            if on_slide_enriched is not None:
                try:
                    on_slide_enriched(row["slide"], {
                        "slide": row["slide"],
                        "summary": result["summary"],
                        "slide_content": result["slide_content"],
                        "lecturer_additions": result["lecturer_additions"],
                        "key_takeaways": result["key_takeaways"],
                    })
                except Exception:
                    pass
            batch_results.append(result)
        return batch_results

    results: list[dict] = []
    batches = chunk_alignment_rows(alignment, enrich_batch_size)
    with ThreadPoolExecutor(max_workers=enrich_max_workers) as pool:
        futures = [pool.submit(enrich_batch, batch) for batch in batches]
        for future in as_completed(futures):
            results.extend(future.result())

    results.sort(key=lambda entry: entry["slide"])
    wall_duration_ms = int((time.perf_counter() - stage_started) * 1000)
    summary = (
        f"Slide enrichment complete. total_tokens={usage_totals['total_tokens']} "
        f"(input={usage_totals['input_tokens']}, output={usage_totals['output_tokens']}), "
        f"retries={usage_totals['retries']}, fallbacks={usage_totals['fallbacks']}, "
        f"fallback_reasons=truncated_json:{failure_reason_counts['truncated_json']}"
        f"|empty_payload:{failure_reason_counts['empty_payload']}"
        f"|connection_error:{failure_reason_counts['connection_error']}"
        f"|other_error:{failure_reason_counts['other_error']}, "
        f"api_duration_ms={usage_totals['duration_ms']}, wall_duration_ms={wall_duration_ms}"
    )
    print(f"✅ {summary}", flush=True)
    return results
