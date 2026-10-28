"""Sound effects made from scratch, so there's nothing to license: a whoosh for scene changes and a pop for
the opening headline."""
from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

SR = 48000


def _write(path: Path, stereo: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (np.clip(stereo, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(data.tobytes())


def _lowpass(x: np.ndarray, cutoff: np.ndarray) -> np.ndarray:
    """One-pole low-pass filter whose cutoff can change every sample (for the whoosh's sweep)."""
    a = 1 - np.exp(-2 * np.pi * cutoff / SR)
    y = np.empty_like(x)
    acc = 0.0
    for i in range(len(x)):
        acc += a[i] * (x[i] - acc)
        y[i] = acc
    return y


def whoosh(seconds: float = 0.55, peak_at: float = 0.6, seed: int = 7) -> np.ndarray:
    n = int(SR * seconds)
    t = np.linspace(0, 1, n)
    noise = np.random.default_rng(seed).normal(0, 1, n)
    # Bright as it rushes past, duller as it leaves.
    sweep = np.where(t < peak_at, 400 + 5600 * (t / peak_at) ** 2, 6000 - 4500 * (t - peak_at) / (1 - peak_at))
    band = _lowpass(noise, sweep) - _lowpass(noise, sweep / 6)
    env = np.where(t < peak_at, (t / peak_at) ** 2.5, np.exp(-(t - peak_at) * 14))
    mono = band * env
    mono /= np.abs(mono).max() + 1e-9
    pan = np.clip(t * 1.4 - 0.2, 0, 1)  # left to right
    return np.stack([mono * np.cos(pan * np.pi / 2), mono * np.sin(pan * np.pi / 2)], axis=1) * 0.7


def pop(seconds: float = 0.14) -> np.ndarray:
    n = int(SR * seconds)
    t = np.arange(n) / SR
    freq = 500 + 1100 * np.exp(-t / 0.018)
    phase = 2 * np.pi * np.cumsum(freq) / SR
    env = np.minimum(t / 0.002, 1) * np.exp(-t / 0.035)
    mono = np.sin(phase) * env
    mono /= np.abs(mono).max() + 1e-9
    return np.stack([mono, mono], axis=1) * 0.6


def make_all(folder: Path) -> dict[str, Path]:
    paths = {"whoosh": folder / "whoosh.wav", "pop": folder / "pop.wav"}
    if not paths["whoosh"].exists():
        _write(paths["whoosh"], whoosh())
    if not paths["pop"].exists():
        _write(paths["pop"], pop())
    return paths
