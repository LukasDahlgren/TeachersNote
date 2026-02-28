from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse, urlunparse

try:
    import httpx
except ModuleNotFoundError:
    class _HttpxFallback:
        class TimeoutException(Exception):
            pass

        class HTTPError(Exception):
            pass

        class Timeout:
            def __init__(self, *args, **kwargs):
                pass

        class Client:
            def __init__(self, *args, **kwargs):
                raise ModuleNotFoundError("No module named 'httpx'")

    httpx = _HttpxFallback()  # type: ignore[assignment]

RecordingSourceKind = Literal["file", "url"]


class RemoteMediaDownloadError(ValueError):
    """User-facing validation/download error for remote media URLs."""


def _parse_allowed_extensions(raw: str) -> set[str]:
    extensions: set[str] = set()
    for item in raw.split(","):
        token = item.strip().lower()
        if not token:
            continue
        if not token.startswith("."):
            token = f".{token}"
        extensions.add(token)
    return extensions


DEFAULT_ALLOWED_EXTENSIONS = _parse_allowed_extensions(
    os.getenv("REMOTE_MEDIA_ALLOWED_EXTENSIONS", ".mp4,.mov,.webm,.wav,.m4a,.mp3")
)
DEFAULT_MAX_BYTES = int(os.getenv("REMOTE_MEDIA_MAX_BYTES", "524288000"))
DEFAULT_CONNECT_TIMEOUT_SEC = float(os.getenv("REMOTE_MEDIA_CONNECT_TIMEOUT_SEC", "10"))
DEFAULT_READ_TIMEOUT_SEC = float(os.getenv("REMOTE_MEDIA_READ_TIMEOUT_SEC", "120"))
DEFAULT_TOTAL_TIMEOUT_SEC = float(os.getenv("REMOTE_MEDIA_TOTAL_TIMEOUT_SEC", "600"))


def redact_url_for_logs(url: str) -> str:
    parsed = urlparse((url or "").strip())
    if not parsed.scheme or not parsed.netloc:
        return "<invalid-url>"
    base = urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))
    return f"{base}?<redacted>" if parsed.query else base


def media_extension_from_url(url: str) -> str:
    return Path(urlparse(url).path).suffix.lower()


def validate_remote_media_url(
    url: str,
    *,
    allowed_extensions: set[str] | None = None,
) -> str:
    normalized = (url or "").strip()
    if not normalized:
        raise RemoteMediaDownloadError(
            "Provide a non-empty recording URL when using audio_url."
        )

    parsed = urlparse(normalized)
    if parsed.scheme.lower() != "https":
        raise RemoteMediaDownloadError("Recording URL must use HTTPS.")
    if not parsed.netloc:
        raise RemoteMediaDownloadError("Recording URL must include a valid host.")

    extension = Path(parsed.path).suffix.lower()
    allowed = allowed_extensions or DEFAULT_ALLOWED_EXTENSIONS
    if extension not in allowed:
        raise RemoteMediaDownloadError(
            "Recording URL must point to a direct media file with one of: "
            + ", ".join(sorted(allowed))
        )

    return normalized


def resolve_recording_source(
    *,
    audio_present: bool,
    audio_url: str | None,
) -> tuple[RecordingSourceKind, str | None]:
    normalized_url = (audio_url or "").strip()
    has_url = bool(normalized_url)

    if audio_present and has_url:
        raise RemoteMediaDownloadError(
            "Provide exactly one recording source: either 'audio' file or 'audio_url', not both."
        )
    if not audio_present and not has_url:
        raise RemoteMediaDownloadError(
            "Provide a recording source: either 'audio' file or 'audio_url'."
        )
    if audio_present:
        return "file", None
    return "url", normalized_url


def download_remote_media_to_path(
    url: str,
    destination: Path,
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
    connect_timeout_sec: float = DEFAULT_CONNECT_TIMEOUT_SEC,
    read_timeout_sec: float = DEFAULT_READ_TIMEOUT_SEC,
    total_timeout_sec: float = DEFAULT_TOTAL_TIMEOUT_SEC,
) -> None:
    normalized = validate_remote_media_url(url)
    safe_url = redact_url_for_logs(normalized)
    destination.parent.mkdir(parents=True, exist_ok=True)

    timeout = httpx.Timeout(
        connect=connect_timeout_sec,
        read=read_timeout_sec,
        write=read_timeout_sec,
        pool=connect_timeout_sec,
    )
    started = time.monotonic()
    bytes_written = 0

    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            with client.stream("GET", normalized) as response:
                if response.status_code >= 400:
                    raise RemoteMediaDownloadError(
                        f"Failed to download recording URL ({safe_url}): HTTP {response.status_code}."
                    )

                content_type = response.headers.get("content-type", "")
                normalized_content_type = content_type.split(";", 1)[0].strip().lower()
                if normalized_content_type and not (
                    normalized_content_type.startswith("video/")
                    or normalized_content_type.startswith("audio/")
                    or normalized_content_type == "application/octet-stream"
                ):
                    raise RemoteMediaDownloadError(
                        f"Recording URL returned unsupported content type '{normalized_content_type}' "
                        f"({safe_url})."
                    )

                content_length = response.headers.get("content-length")
                if content_length:
                    try:
                        expected_size = int(content_length)
                    except ValueError:
                        expected_size = 0
                    if expected_size > max_bytes:
                        raise RemoteMediaDownloadError(
                            f"Recording URL exceeds size limit ({expected_size} bytes > {max_bytes} bytes)."
                        )

                with destination.open("wb") as output:
                    for chunk in response.iter_bytes():
                        if not chunk:
                            continue
                        elapsed = time.monotonic() - started
                        if elapsed > total_timeout_sec:
                            raise RemoteMediaDownloadError(
                                f"Downloading recording URL exceeded total timeout ({int(total_timeout_sec)}s)."
                            )
                        bytes_written += len(chunk)
                        if bytes_written > max_bytes:
                            raise RemoteMediaDownloadError(
                                f"Recording URL exceeds size limit ({bytes_written} bytes > {max_bytes} bytes)."
                            )
                        output.write(chunk)

        if bytes_written <= 0:
            raise RemoteMediaDownloadError("Recording URL download returned no media bytes.")
    except RemoteMediaDownloadError:
        destination.unlink(missing_ok=True)
        raise
    except httpx.TimeoutException as exc:
        destination.unlink(missing_ok=True)
        raise RemoteMediaDownloadError(
            f"Timed out while downloading recording URL ({safe_url})."
        ) from exc
    except httpx.HTTPError as exc:
        destination.unlink(missing_ok=True)
        raise RemoteMediaDownloadError(
            f"Failed to download recording URL ({safe_url}): {exc.__class__.__name__}."
        ) from exc
    except OSError as exc:
        destination.unlink(missing_ok=True)
        raise RemoteMediaDownloadError(
            f"Failed to store downloaded recording file: {exc}"
        ) from exc
    except ModuleNotFoundError as exc:
        destination.unlink(missing_ok=True)
        raise RemoteMediaDownloadError(
            "Server dependency missing for URL downloads: install 'httpx'."
        ) from exc
