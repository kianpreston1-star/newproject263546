"""Builds the finished video with FFmpeg. Each shot is rendered on its own (a broken stock clip then costs one shot,
not the video), with a smooth slow zoom, a punch-in on scene changes and a colour grade. A final pass joins them and
adds the captions, progress bar, sound effects, background music that dips under the voice, and loudness levelling."""
from __future__ import annotations

import json
import logging
import math
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .themes import Theme, ffmpeg_color

log = logging.getLogger(__name__)

W, H, FPS = 1080, 1920, 30
MAX_SHOT = 3.2  # seconds; longer scenes are cut into several shots to keep the pace up
TELEGRAM_LIMIT_MB = 46  # bots can send files up to 50 MB; the video is sized to fit


class RenderError(RuntimeError):
    pass


@dataclass
class Shot:
    start: float
    end: float
    kind: str  # "video", "image" or "background"
    path: Path | None = None
    src_duration: float = 0.0
    scene_start: bool = False  # first shot of a scene: gets the punch-in and the whoosh
    zoom_out: bool = False
    offset: float = -1.0  # where to start in the clip (seconds); -1 picks automatically
    dim: float = 0.0  # darken a busy background so characters and captions stand out

    @property
    def duration(self) -> float:
        return self.end - self.start


def plan_shots(spans: list[tuple[float, float]], total: float) -> list[tuple[int, float, float, bool]]:
    """Cuts the timeline into shots: (scene index, start, end, first shot of its scene). Shots are back to back,
    so a scene's shot also covers the pause before the next scene."""
    starts = [0.0] + [s for s, _ in spans[1:]]
    ends = starts[1:] + [total]
    out = []
    for i, (a, b) in enumerate(zip(starts, ends)):
        n = max(1, math.ceil((b - a) / MAX_SHOT))
        step = (b - a) / n
        for k in range(n):
            out.append((i, round(a + k * step, 3), round(a + (k + 1) * step, 3), k == 0))
    return out


def video_kbps(duration: float, audio_kbps: int = 160) -> int:
    """Bitrate cap that keeps the file under Telegram's bot upload limit (and is plenty for phones)."""
    budget = TELEGRAM_LIMIT_MB * 8 * 1000 / max(duration, 1) - audio_kbps
    return int(max(2500, min(8000, budget)))


def probe(path: Path) -> tuple[int, int, float]:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height:format=duration", "-of", "json", str(path)],
                         capture_output=True, text=True, timeout=60)
    if out.returncode:
        raise RenderError(f"Can't read {path.name}")
    d = json.loads(out.stdout)
    st = (d.get("streams") or [{}])[0]
    return int(st.get("width", 0)), int(st.get("height", 0)), float(d.get("format", {}).get("duration", 0) or 0)


def _zoom(frames: int, zoom_out: bool, punch: bool, amount: float = 0.09) -> str:
    """A slow zoom using perspective, which moves smoothly by fractions of a pixel (zoompan judders)."""
    n = max(frames - 1, 1)
    z = f"(1+{amount}*(1-in/{n}))" if zoom_out else f"(1+{amount}*in/{n})"
    if punch:  # a quick push that settles in a fifth of a second
        z = f"({z}+0.07*max(0,1-in/6))"
    x0, y0 = f"W*(1-1/{z})/2", f"H*(1-1/{z})/2"
    return (f"perspective=x0='{x0}':y0='{y0}':x1='W-{x0}':y1='{y0}':x2='{x0}':y2='H-{y0}':x3='W-{x0}':"
            f"y3='H-{y0}':interpolation=linear:eval=frame")


def _grade(theme: Theme) -> str:
    return f"eq=contrast={theme.contrast}:saturation={theme.saturation},vignette=angle=PI/5"


def shot_command(shot: Shot, theme: Theme, out: Path, index: int) -> list[str]:
    frames = max(1, round(shot.duration * FPS))
    dur = f"{frames / FPS:.3f}"
    zoom = _zoom(frames, shot.zoom_out, shot.scene_start and index > 0)
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    if shot.kind == "video":
        src = shot.src_duration
        offset, slow = 0.0, 1.0
        if shot.offset >= 0:
            offset = shot.offset
        elif src > shot.duration + 1.2:
            offset = min(1.0, (src - shot.duration) / 3)  # skip fade-ins at the very start of stock clips
        elif 0 < src < shot.duration:
            slow = min(shot.duration / src, 1.5)  # slow a short clip down a little rather than repeat it
        if 0 < (src - offset) * slow < shot.duration:
            cmd += ["-stream_loop", "-1"]
        cmd += ["-ss", f"{offset:.2f}", "-i", str(shot.path)]
        vf = (f"setpts={slow:.3f}*(PTS-STARTPTS),fps={FPS},scale={W}:{H}:force_original_aspect_ratio=increase:"
              f"flags=bicubic,crop={W}:{H},setsar=1,{zoom},{_grade(theme)}")
        if shot.dim:
            vf += f",eq=brightness=-{shot.dim}"
        cmd += ["-vf", vf]
    elif shot.kind == "image":
        # The photo sits on a blurred, darkened copy of itself, so any shape of photo fills the frame.
        cmd += ["-loop", "1", "-framerate", str(FPS), "-t", dur, "-i", str(shot.path)]
        fc = (f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=28:2,"
              f"eq=brightness=-0.12:saturation=1.1[bg];"
              f"[0:v]scale=980:1300:force_original_aspect_ratio=decrease[fg];"
              f"[bg][fg]overlay=(W-w)/2:(H-h)/2-60,format=yuv420p,setsar=1,{zoom},{_grade(theme)}[v]")
        cmd += ["-filter_complex", fc, "-map", "[v]"]
    else:
        dark, glow = (ffmpeg_color(c) for c in theme.background)  # dark-glow-dark: a band of colour on black
        cmd += ["-f", "lavfi", "-i", f"gradients=s={W}x{H}:r={FPS}:d={dur}:c0={dark}:c1={glow}:c2={dark}:nb_colors=3:"
                                     f"speed=0.012:type={'linear' if index % 2 else 'radial'}:seed={index * 7919}"]
        cmd += ["-vf", f"format=yuv420p,setsar=1,noise=alls=6:allf=t,{zoom}"]
    cmd += ["-t", dur, "-an", "-r", str(FPS), "-c:v", "libx264", "-preset", "ultrafast", "-crf", "15",
            "-pix_fmt", "yuv420p", str(out)]
    return cmd


def _run(cmd: list[str], what: str, timeout: int = 1800) -> None:
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if p.returncode:
        err = (p.stderr or "").strip().splitlines()[-3:]
        raise RenderError(f"FFmpeg failed while {what}: {' / '.join(err) or 'no details'}")


def render_shots(shots: list[Shot], theme: Theme, work: Path) -> list[Path]:
    segs = []
    for i, shot in enumerate(shots):
        out = work / f"shot{i:03d}.mp4"
        try:
            # A few seconds of video takes well under a minute even on an old laptop; a hang means a bad file.
            _run(shot_command(shot, theme, out, i), f"preparing shot {i + 1}", timeout=int(90 + 30 * shot.duration))
        except (RenderError, subprocess.TimeoutExpired) as e:
            log.warning("Shot %d failed (%s); using a plain background instead", i + 1, e)
            _run(shot_command(Shot(shot.start, shot.end, "background", scene_start=shot.scene_start), theme, out, i),
                 f"preparing shot {i + 1}")
        segs.append(out)
    return segs


def final_command(work: Path, segs: list[Path], duration: float, theme: Theme, music: Path | None,
                  music_volume: float, sfx: dict[str, Path], whooshes: list[float], out: Path,
                  preset: str = "veryfast", overlays: list = (), pops: tuple = (0.04,)) -> list[str]:
    (work / "shots.txt").write_text("".join(f"file '{p.name}'\n" for p in segs))
    d = f"{duration:.3f}"
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", "shots.txt",
           "-i", "voice.wav"]
    idx = 2
    music_idx = None
    if music:
        cmd += ["-stream_loop", "-1", "-i", str(music)]
        music_idx, idx = idx, idx + 1
    cmd += ["-i", str(sfx["whoosh"]), "-i", str(sfx["pop"])]
    whoosh_idx, pop_idx = idx, idx + 1
    idx += 2
    fmt = "aformat=sample_rates=48000:channel_layouts=stereo"
    f = ["[0:v]setpts=PTS-STARTPTS,format=yuv420p[base]"]
    below = "base"
    for n, ov in enumerate(overlays):  # characters, the photo card: anything laid over the footage
        cmd += ov.args
        f.append(f"[{idx}:v]{ov.prep}[ov{n}]")
        f.append(f"[{below}][ov{n}]overlay=x='{ov.x}':y='{ov.y}':eval=frame:eof_action=pass,format=yuv420p[lay{n}]")
        below, idx = f"lay{n}", idx + 1
    f += [
        f"color=c={ffmpeg_color(theme.accent)}:s={W}x14:r={FPS}:d={d}[bar]",
        f"[{below}][bar]overlay=x='-w+w*t/{d}':y=0:eval=frame:shortest=1[barred]",
        "[barred]ass=filename=captions.ass:fontsdir=fonts[vout]",
        f"[1:a]{fmt},apad,atrim=duration={d},asplit=2[voice][key]",
    ]
    mix = ["[voice]"]
    if music_idx is not None:
        f.append(f"[{music_idx}:a]{fmt},atrim=duration={d},volume={music_volume},afade=t=in:d=0.8,"
                 f"afade=t=out:st={max(duration - 1.5, 0):.2f}:d=1.5[bed]")
        f.append("[bed][key]sidechaincompress=threshold=0.025:ratio=5:attack=20:release=400:makeup=1[music]")
        mix.append("[music]")
    else:
        f.append("[key]anullsink")
    if whooshes:
        n = len(whooshes)
        f.append(f"[{whoosh_idx}:a]{fmt},volume=0.33,asplit={n}" + "".join(f"[w{i}]" for i in range(n)) if n > 1
                 else f"[{whoosh_idx}:a]{fmt},volume=0.33[w0]")
        for i, t in enumerate(whooshes):
            ms = max(0, int(t * 1000))
            f.append(f"[w{i}]adelay={ms}|{ms}[wd{i}]")
            mix.append(f"[wd{i}]")
    if pops:  # the headline's pop, plus each character popping up in two-character videos
        n = len(pops)
        f.append(f"[{pop_idx}:a]{fmt},volume=0.4" + (f",asplit={n}" + "".join(f"[p{i}]" for i in range(n))
                                                       if n > 1 else "[p0]"))
        for i, t in enumerate(pops):
            ms = max(0, int(t * 1000))
            f.append(f"[p{i}]adelay={ms}|{ms}[pd{i}]")
            mix.append(f"[pd{i}]")
    f.append("".join(mix) + f"amix=inputs={len(mix)}:duration=first:normalize=0,"
             "loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[aout]")
    kbps = video_kbps(duration)
    cmd += ["-filter_complex", ";".join(f), "-map", "[vout]", "-map", "[aout]", "-t", d,
            "-c:v", "libx264", "-preset", preset, "-crf", "21", "-maxrate", f"{kbps}k", "-bufsize", f"{kbps * 2}k",
            "-profile:v", "high", "-pix_fmt", "yuv420p", "-r", str(FPS), "-g", str(FPS * 2),
            "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-movflags", "+faststart", str(out)]
    return cmd


def finish(work: Path, segs: list[Path], duration: float, theme: Theme, music: Path | None, music_volume: float,
           sfx: dict[str, Path], whooshes: list[float], out: Path, preset: str = "veryfast",
           overlays: list = (), pops: tuple = (0.04,)) -> Path:
    cmd = final_command(work, segs, duration, theme, music, music_volume, sfx, whooshes, out, preset, overlays,
                        pops)
    p = subprocess.run(cmd, cwd=work, capture_output=True, text=True, timeout=3600)
    if p.returncode:
        err = (p.stderr or "").strip().splitlines()[-4:]
        raise RenderError("FFmpeg failed while putting the video together: " + " / ".join(err))
    return out


def ffmpeg_ok() -> tuple[bool, str]:
    """FFmpeg must be installed with libass (captions); Ubuntu's package has it."""
    try:
        p = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True, timeout=30)
    except FileNotFoundError:
        return False, "FFmpeg isn't installed. Install it with: sudo apt install ffmpeg"
    missing = [n for n in ("ass", "perspective", "gradients", "sidechaincompress", "loudnorm")
               if f" {n} " not in p.stdout]
    if missing:
        return False, (f"Your FFmpeg is missing these filters: {', '.join(missing)}. "
                       "Install Ubuntu's: sudo apt install ffmpeg")
    decoders = subprocess.run(["ffmpeg", "-hide_banner", "-decoders"], capture_output=True, text=True, timeout=30)
    if "librsvg" not in decoders.stdout:
        return False, ("Your FFmpeg can't draw the cartoon characters (no librsvg). "
                       "Install Ubuntu's: sudo apt install ffmpeg")
    version = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, timeout=30).stdout
    return True, " ".join(version.split()[:3]) or "FFmpeg is ready"
