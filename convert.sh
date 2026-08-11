#!/bin/bash
# Dùng: ./convert.sh ten_bai.mid
#       ./convert.sh ten_bai.mid --bpm 90
# Kết quả mỗi bài:
#   track_A_single.ghost.txt   ← Track A (giai điệu)
#   track_B_harmony.ghost.txt  ← Track B (hòa âm)
#   track_C_bass.ghost.txt     ← Track C (bass)
#   gop_ABC.mml.txt            ← MML@A,B,C;
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

if [ -z "$1" ]; then
  echo "Dùng: ./convert.sh ten_file.mid"
  echo "  hoặc: ./convert.sh input/ten_file.mid"
  echo ""
  echo "Folder: ~/Documents/GhostStory-Piano"
  echo "Mỗi lần chạy tạo: output/<ten_bai>/track_A_single.ghost.txt"
  exit 1
fi

IN="$1"
shift

if [ ! -f "$IN" ] && [ -f "input/$IN" ]; then
  IN="input/$IN"
fi
if [ ! -f "$IN" ]; then
  echo "Không thấy: $IN"
  echo "Hãy bỏ file .mid vào: $DIR/input/"
  exit 1
fi

NAME="$(basename "$IN" .mid)"
NAME="$(basename "$NAME" .midi)"
# normalize giống python safe_name đơn giản
SAFE="$(echo "$NAME" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/_/g; s/^_+//; s/_+$//')"
OUTDIR="output/${SAFE}"

python3 midi_to_ghoststory.py "$IN" -o "$OUTDIR" --limit 3000 "$@"

echo ""
echo "Folder kết quả: $DIR/$OUTDIR"
echo "  → A: track_A_single.ghost.txt"
echo "  → B: track_B_harmony.ghost.txt"
echo "  → C: track_C_bass.ghost.txt"
echo "  → gộp: gop_ABC.mml.txt"
# macOS: mở folder (bỏ qua lỗi nếu không mở được)
if command -v open >/dev/null 2>&1; then
  open "$OUTDIR" 2>/dev/null || true
fi
