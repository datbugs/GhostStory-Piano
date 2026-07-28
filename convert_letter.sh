#!/bin/bash
# Letter notes → Ghost Story
# Dùng: ./convert_letter.sh ten_bai.txt --bpm 100
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

if [ -z "$1" ]; then
  echo "Dùng: ./convert_letter.sh ten_bai.txt [--bpm 100] [--title \"Ten Bai\"]"
  echo ""
  echo "1) Paste letter notes vào input/letter_notes/ten_bai.txt"
  echo "   Format: 4|G-G--G--F-e-C-------------|"
  echo "2) Chạy script này"
  echo "3) Copy output/<ten>/track_A_ghoststory.txt → Track A"
  exit 1
fi

IN="$1"
shift
if [ ! -f "$IN" ] && [ -f "input/letter_notes/$IN" ]; then
  IN="input/letter_notes/$IN"
fi
if [ ! -f "$IN" ]; then
  echo "Không thấy: $IN"
  echo "Hãy tạo: $DIR/input/letter_notes/"
  exit 1
fi

python3 letter_notes_to_ghoststory.py "$IN" --limit 3000 "$@"

OUTDIR=$(ls -td output/*/ 2>/dev/null | head -1)
if command -v open >/dev/null 2>&1 && [ -d "$OUTDIR" ]; then
  open "$OUTDIR"
fi
