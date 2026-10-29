"""The voiceover (Kokoro, a small natural-sounding text-to-speech model that runs on the laptop's processor) and
word-by-word timings for the captions (Whisper listens to the voiceover and reports when each word is said)."""
from __future__ import annotations

import difflib
import logging
import os
import re
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .captions import Word
from .themes import kokoro_lang

log = logging.getLogger(__name__)

SR = 24000  # Kokoro's sample rate
KOKORO_FILES = {
    "kokoro-v1.0.onnx": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx",
    "voices-v1.0.bin": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin",
}
SCENE_GAP = 0.14  # pause between scenes: enough to breathe, short enough to keep the pace


@dataclass
class Track:
    audio: np.ndarray  # mono float32 at SR
    spans: list[tuple[float, float]]  # (start, end) seconds of each scene's speech

    @property
    def duration(self) -> float:
        return len(self.audio) / SR


def trim_silence(a: np.ndarray, threshold: float = 0.01, keep: float = 0.03) -> np.ndarray:
    loud = np.flatnonzero(np.abs(a) > threshold)
    if not len(loud):
        return a
    pad = int(keep * SR)
    return a[max(0, loud[0] - pad):min(len(a), loud[-1] + pad)]


def write_wav(path: Path, audio: np.ndarray, sr: int = SR) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes())


class Voice:
    def __init__(self, models_dir: Path):
        self.dir = Path(models_dir)
        self._kokoro = None

    def ready(self) -> bool:
        return all((self.dir / f).exists() for f in KOKORO_FILES)

    def _model(self):
        if self._kokoro is None:
            if not self.ready():
                raise RuntimeError("The voice model isn't downloaded yet. Run: trendclips setup")
            from kokoro_onnx import Kokoro

            # It warns on every line that its word count differs from the phonemes'; harmless and noisy.
            logging.getLogger("phonemizer").setLevel(logging.ERROR)
            self._kokoro = Kokoro(str(self.dir / "kokoro-v1.0.onnx"), str(self.dir / "voices-v1.0.bin"))
        return self._kokoro

    def speak(self, text: str, voice: str, speed: float, pitch: float = 1.0) -> np.ndarray:
        """Speech at `speed`. A pitch other than 1 is made by reading slower (or faster) and then playing it back
        faster (or slower): the pace comes out the same, the voice higher or deeper, like a cartoon."""
        pitch = min(max(pitch, 0.7), 1.4)
        audio, sr = self._model().create(text, voice=voice, speed=speed / pitch, lang=kokoro_lang(voice))
        audio = resample(np.asarray(audio, dtype=np.float32), int(sr * pitch), SR)
        return trim_silence(audio)

    def track(self, lines: list[tuple[str, str, float, float]]) -> Track:
        """Speaks (text, voice, speed, pitch) lines one after another with a short pause between them."""
        pieces, spans, t = [], [], 0.0
        gap = np.zeros(int(SCENE_GAP * SR), dtype=np.float32)
        for i, (text, voice, speed, pitch) in enumerate(lines):
            a = self.speak(text, voice, speed, pitch)
            spans.append((t, t + len(a) / SR))
            pieces.append(a)
            t += len(a) / SR
            if i < len(lines) - 1:
                pieces.append(gap)
                t += SCENE_GAP
        audio = np.concatenate(pieces) if pieces else np.zeros(SR, dtype=np.float32)
        peak = float(np.abs(audio).max() or 1)
        return Track((audio / peak * 0.89).astype(np.float32), spans)


def resample(a: np.ndarray, sr_in: int, sr_out: int) -> np.ndarray:
    n = int(round(len(a) * sr_out / sr_in))
    return np.interp(np.linspace(0, len(a) - 1, n), np.arange(len(a)), a).astype(np.float32)


def _norm(word: str) -> str:
    return re.sub(r"[^a-z0-9]", "", word.lower())


def estimate_times(words: list[str], start: float, end: float) -> list[tuple[float, float]]:
    """Spreads words across a stretch of speech by length, with extra time at punctuation."""
    weights = []
    for w in words:
        extra = 5 if w.endswith((".", "!", "?")) else 3 if w.endswith((",", ";", ":")) else 0
        weights.append(len(_norm(w)) + 3 + extra)
    total = sum(weights) or 1
    out, t = [], start
    for wt in weights:
        d = (end - start) * wt / total
        out.append((t, t + d))
        t += d
    return out


def align(words: list[str], heard: list[tuple[str, float, float]], start: float,
          end: float) -> list[tuple[float, float]]:
    """Gives each script word the time Whisper heard it. Whisper's spelling doesn't matter (it may hear "Alon's"
    for "Elon's"); words it missed get times spread between their neighbours."""
    a = [_norm(w) for w in words]
    b = [_norm(w) for w, _, _ in heard]
    times: list[tuple[float, float] | None] = [None] * len(words)
    for blk in difflib.SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks():
        for k in range(blk.size):
            _, s, e = heard[blk.b + k]
            times[blk.a + k] = (s, e)
    i = 0
    while i < len(words):
        if times[i] is not None:
            i += 1
            continue
        j = i
        while j < len(words) and times[j] is None:
            j += 1
        left = times[i - 1][1] if i > 0 else start
        right = times[j][0] if j < len(words) else end
        if right <= left:
            right = left + 0.08 * (j - i)
        for k, span in enumerate(estimate_times(words[i:j], left, right)):
            times[i + k] = span
        i = j
    out, last = [], start
    for s, e in times:  # keep them in order and inside the scene
        s = min(max(s, last, start), end)
        e = min(max(e, s + 0.05), end + 0.2)
        out.append((s, e))
        last = s
    return out


class Timer:
    """Word timings from Whisper's small English model; falls back to estimates if it can't load."""

    _model = None

    def __init__(self, models_dir: Path):
        self.dir = Path(models_dir)

    def _whisper(self):
        if Timer._model is None:
            from faster_whisper import WhisperModel

            Timer._model = WhisperModel("base.en", device="cpu", compute_type="int8",
                                        cpu_threads=os.cpu_count() or 2, download_root=str(self.dir))
        return Timer._model

    def heard(self, track: Track) -> list[tuple[str, float, float]]:
        try:
            audio16 = resample(track.audio, SR, 16000)
            segments, _ = self._whisper().transcribe(audio16, language="en", word_timestamps=True, beam_size=1,
                                                     vad_filter=False, condition_on_previous_text=False)
            return [(w.word.strip(), float(w.start), float(w.end)) for s in segments for w in s.words]
        except Exception as e:  # any failure just means estimated timings
            log.warning("Word timing fell back to estimates (%s: %s)", type(e).__name__, e)
            return []

    def words(self, track: Track, texts: list[str], keywords: list[list[str]]) -> list[Word]:
        heard = self.heard(track)
        out = []
        for i, (text, (start, end)) in enumerate(zip(texts, track.spans)):
            tokens = text.split()
            near = [h for h in heard if start - 0.25 <= (h[1] + h[2]) / 2 <= end + 0.25]
            times = align(tokens, near, start, end) if near else estimate_times(tokens, start, end)
            keys = {_norm(k) for k in keywords[i]} if i < len(keywords) else set()
            for tok, (s, e) in zip(tokens, times):
                out.append(Word(tok, round(s, 3), round(e, 3), i, _norm(tok) in keys))
        return out
