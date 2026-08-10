import subprocess
import tempfile
import os
import time
import threading
import logging

import whisper

logger = logging.getLogger(__name__)

model = whisper.load_model("base")

# whisper's model object is not safe to use from two threads at once: if a
# worker for the old station is still transcribing when a worker for the new
# station starts, the two passes interleave and produce mixed-up text. Only one
# transcription may run at a time.
_whisper_lock = threading.Lock()


class CaptureError(Exception):
    """Audio could not be captured from the stream."""


def _friendly_error(stderr_text):
    """Turn a wall of FFmpeg output into one line a human can act on."""
    text    = (stderr_text or "").strip()
    lowered = text.lower()

    if "403" in lowered or "forbidden" in lowered:
        return "Station refused the connection (403 Forbidden) — it blocks non-browser clients."
    if "404" in lowered or "not found" in lowered:
        return "Stream URL not found (404) — the address is wrong or retired."
    if "401" in lowered or "unauthorized" in lowered:
        return "Stream requires authentication (401)."
    if "connection refused" in lowered:
        return "Connection refused — the station's server is down or the port is closed."
    if "name or service not known" in lowered or "failed to resolve" in lowered:
        return "Station address could not be resolved — the URL is dead or misspelled."
    if "timed out" in lowered or "timeout" in lowered:
        return "Connection to the station timed out."
    if "invalid data found" in lowered:
        return "Stream carried no playable audio (wrong URL, or a webpage instead of a stream)."
    if "server returned 5" in lowered:
        return "The station's server returned an error (5xx)."

    lines = [l for l in text.splitlines() if l.strip()]
    return lines[-1] if lines else "Unknown capture error."


def _run_ffmpeg(cmd, chunk_seconds, stop_event):
    """Run FFmpeg, aborting the moment stop_event is set.

    Returns (returncode, stderr_text), or None if we were told to stop.
    """
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    deadline = time.monotonic() + chunk_seconds + 15

    while True:
        try:
            _, stderr = proc.communicate(timeout=0.5)
            return proc.returncode, stderr.decode(errors="replace")
        except subprocess.TimeoutExpired:
            # Switched station or stopped — kill the capture now instead of
            # letting it record another 15s of a station nobody is listening to.
            if stop_event is not None and stop_event.is_set():
                proc.kill()
                proc.communicate()
                return None
            if time.monotonic() > deadline:
                proc.kill()
                proc.communicate()
                raise CaptureError("Connection to the station timed out.")


def capture_and_transcribe(stream_url, chunk_seconds=15, stop_event=None):
    """Record a chunk of a stream and transcribe it.

    Returns the text, or None if nothing was said or we were told to stop.
    Raises CaptureError when the stream itself could not be read.
    """
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        cmd = [
            "ffmpeg", "-y",
            "-user_agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "-headers", "Icy-MetaData: 0\r\n",
            "-fflags", "nobuffer+discardcorrupt",
            "-flags", "low_delay",
            "-rtbufsize", "32",
            "-i", stream_url,
            "-ss", "2",
            "-t", str(chunk_seconds),
            "-ar", "16000",
            "-ac", "1",
            "-f", "wav",
            tmp_path,
        ]

        try:
            result = _run_ffmpeg(cmd, chunk_seconds, stop_event)
        except FileNotFoundError:
            raise CaptureError(
                "FFmpeg is not installed or not on PATH — audio cannot be captured."
            )

        if result is None:
            return None

        returncode, stderr_text = result

        if returncode != 0:
            message = _friendly_error(stderr_text)
            logger.warning("FFmpeg failed for %s: %s", stream_url, message)
            raise CaptureError(message)

        if stop_event is not None and stop_event.is_set():
            return None

        # One transcription at a time — see _whisper_lock above.
        with _whisper_lock:
            # The lock may have been held by the previous station's worker for
            # a while; re-check before spending CPU on audio nobody wants.
            if stop_event is not None and stop_event.is_set():
                return None
            whisper_result = model.transcribe(tmp_path)

        text = whisper_result["text"].strip()
        return text or None

    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
