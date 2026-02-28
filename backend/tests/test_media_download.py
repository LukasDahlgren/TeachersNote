import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    import media_download as media_download_module
except ModuleNotFoundError:
    import backend.media_download as media_download_module

RemoteMediaDownloadError = media_download_module.RemoteMediaDownloadError
download_remote_media_to_path = media_download_module.download_remote_media_to_path
redact_url_for_logs = media_download_module.redact_url_for_logs
resolve_recording_source = media_download_module.resolve_recording_source
validate_remote_media_url = media_download_module.validate_remote_media_url


class _DummyResponse:
    def __init__(self, *, status_code: int = 200, headers: dict[str, str] | None = None, chunks: list[bytes] | None = None):
        self.status_code = status_code
        self.headers = headers or {}
        self._chunks = chunks or []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def iter_bytes(self):
        for chunk in self._chunks:
            yield chunk


class _DummyClient:
    def __init__(self, response: _DummyResponse):
        self._response = response

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def stream(self, method: str, url: str):
        return self._response


class RemoteMediaUrlValidationTests(unittest.TestCase):
    def test_accepts_signed_https_mp4_url(self) -> None:
        url = "https://example.org/media/lecture.mp4?token=abc123"
        self.assertEqual(validate_remote_media_url(url), url)

    def test_rejects_non_https_url(self) -> None:
        with self.assertRaises(RemoteMediaDownloadError):
            validate_remote_media_url("http://example.org/media/lecture.mp4")

    def test_rejects_unsupported_extension(self) -> None:
        with self.assertRaises(RemoteMediaDownloadError):
            validate_remote_media_url("https://example.org/media/lecture.m3u8")

    def test_redacts_query_in_log_url(self) -> None:
        raw = "https://example.org/media/lecture.mp4?token=secret-token&expires=123"
        redacted = redact_url_for_logs(raw)
        self.assertIn("?<redacted>", redacted)
        self.assertNotIn("secret-token", redacted)
        self.assertNotIn("expires=123", redacted)


class RecordingSourceResolutionTests(unittest.TestCase):
    def test_file_only_source_is_valid(self) -> None:
        source, audio_url = resolve_recording_source(audio_present=True, audio_url=None)
        self.assertEqual(source, "file")
        self.assertIsNone(audio_url)

    def test_url_only_source_is_valid(self) -> None:
        source, audio_url = resolve_recording_source(
            audio_present=False,
            audio_url="https://example.org/media/lecture.mp4?token=abc",
        )
        self.assertEqual(source, "url")
        self.assertEqual(audio_url, "https://example.org/media/lecture.mp4?token=abc")

    def test_both_sources_are_rejected(self) -> None:
        with self.assertRaises(RemoteMediaDownloadError):
            resolve_recording_source(
                audio_present=True,
                audio_url="https://example.org/media/lecture.mp4",
            )

    def test_missing_sources_are_rejected(self) -> None:
        with self.assertRaises(RemoteMediaDownloadError):
            resolve_recording_source(audio_present=False, audio_url=None)


class RemoteMediaDownloadTests(unittest.TestCase):
    def test_rejects_oversized_content_length(self) -> None:
        response = _DummyResponse(
            headers={
                "content-type": "video/mp4",
                "content-length": "12",
            },
            chunks=[b"1234567890ab"],
        )
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "audio.mp4"
            with patch(f"{media_download_module.__name__}.httpx.Client", return_value=_DummyClient(response)):
                with self.assertRaises(RemoteMediaDownloadError):
                    download_remote_media_to_path(
                        "https://example.org/media/lecture.mp4",
                        destination,
                        max_bytes=10,
                    )
            self.assertFalse(destination.exists())

    def test_rejects_total_timeout(self) -> None:
        response = _DummyResponse(
            headers={"content-type": "video/mp4"},
            chunks=[b"abc"],
        )
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "audio.mp4"
            with patch(f"{media_download_module.__name__}.httpx.Client", return_value=_DummyClient(response)):
                with patch(f"{media_download_module.__name__}.time.monotonic", side_effect=[0.0, 2.0]):
                    with self.assertRaises(RemoteMediaDownloadError):
                        download_remote_media_to_path(
                            "https://example.org/media/lecture.mp4",
                            destination,
                            total_timeout_sec=1,
                        )
            self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
