"""
Voice capture and voice query (`jar listen`).

Speech-to-text runs on Groq's `whisper-large-v3-turbo`, which is on the same
free tier as the rest of Jarvis — no local model, no download, consistent with
the project's "cloud APIs only, keep the device light" constraint.

Two modes:
    jar listen           speak a note -> transcribed -> full capture pipeline
    jar listen --ask     speak a question -> answered from your own notes

Recording uses `sounddevice` (already present) and the stdlib `wave` module, so
there is no extra audio dependency. If a microphone is unavailable you can still
transcribe an existing file with `--file`, which covers phone voice memos.
"""

import queue
import tempfile
import wave
from pathlib import Path

SAMPLE_RATE = 16000  # what Whisper expects
CHANNELS = 1


def _write_wav(path, frames, sample_rate=SAMPLE_RATE):
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(CHANNELS)
        handle.setsampwidth(2)  # int16
        handle.setframerate(sample_rate)
        handle.writeframes(b"".join(frames))


def record_fixed(seconds, sample_rate=SAMPLE_RATE):
    """Record for a fixed duration. Returns the path to a temp WAV."""
    import numpy as np
    import sounddevice as sd

    audio = sd.rec(int(seconds * sample_rate), samplerate=sample_rate,
                   channels=CHANNELS, dtype="int16")
    sd.wait()
    path = Path(tempfile.gettempdir()) / "jarvis_voice.wav"
    _write_wav(path, [np.asarray(audio, dtype="int16").tobytes()], sample_rate)
    return path


def record_until(stop_check, sample_rate=SAMPLE_RATE, max_seconds=300):
    """Record until stop_check() returns True (or max_seconds elapses).

    stop_check is polled between audio blocks, so the caller decides when to
    stop — e.g. when the user presses Enter on another thread.
    """
    import sounddevice as sd

    frames = []
    audio_q = queue.Queue()

    def _callback(indata, _frames, _time, status):  # noqa: ARG001
        audio_q.put(bytes(indata))

    blocks_max = int(max_seconds * sample_rate / 1024)
    with sd.RawInputStream(samplerate=sample_rate, blocksize=1024,
                           channels=CHANNELS, dtype="int16",
                           callback=_callback):
        collected = 0
        while not stop_check() and collected < blocks_max:
            try:
                frames.append(audio_q.get(timeout=0.2))
                collected += 1
            except queue.Empty:
                continue

    path = Path(tempfile.gettempdir()) / "jarvis_voice.wav"
    _write_wav(path, frames, sample_rate)
    return path


def transcribe_file(path):
    """Transcribe any audio file via Groq Whisper. Returns text or None."""
    from jarvis.ai import transcribe

    return transcribe(str(path))


def has_microphone():
    try:
        import sounddevice as sd

        return any(d.get("max_input_channels", 0) > 0 for d in sd.query_devices())
    except Exception:
        return False
