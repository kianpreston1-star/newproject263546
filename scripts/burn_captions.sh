#!/usr/bin/env bash
# Burn captions into a vertical (9:16) video with FFmpeg — the free fallback for
# the render step when you don't use Creatomate/Shotstack.
#
# Usage:  burn_captions.sh <input_video> <subtitles.ass|.srt> [output.mp4]
#
# Style roughly mirrors templates/caption-style.json (white text, black outline,
# bottom-center, lifted above the platform UI safe zone). Edit force_style to taste.
set -euo pipefail

IN="${1:?input video required}"
SUBS="${2:?subtitle file (.ass or .srt) required}"
OUT="${3:-out.mp4}"

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "ffmpeg not found. Install it (e.g. apt-get install ffmpeg)." >&2
  exit 1
fi

# MarginV=90 keeps captions above TikTok/Reels bottom UI. Fontsize is in points.
FORCE_STYLE="FontName=Montserrat,Fontsize=18,Bold=1,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=2,Shadow=1,Alignment=2,MarginV=90"

ffmpeg -y -i "$IN" \
  -vf "subtitles='${SUBS}':force_style='${FORCE_STYLE}'" \
  -c:v libx264 -preset veryfast -crf 20 \
  -c:a copy \
  "$OUT"

echo "wrote $OUT"
