#!/bin/bash
# Ghép MIDI từ parts/ → input/<ten>_gop.mid
# Đặt phần lẻ: parts/ten_bai.mid, parts/ten_bai1.mid, ...
#   hoặc:     parts/ten_bai/ten_bai.mid, parts/ten_bai/ten_bai1.mid, ...
#
# Dùng: ./merge_midi.sh seeyouagain
#       ./merge_midi.sh seeyouagain --convert
#       ./merge_midi.sh seeyouagain --convert --bpm 90
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

if [ -z "$1" ]; then
  echo "Dùng: ./merge_midi.sh ten_bai"
  echo "  tìm: parts/ten_bai.mid, parts/ten_bai1.mid, parts/ten_bai2.mid, ..."
  echo "    hoặc parts/ten_bai/*.mid"
  echo "  ra:  input/ten_bai_gop.mid"
  echo ""
  echo "  ./merge_midi.sh ten_bai --convert         ghép rồi convert luôn"
  echo "  ./merge_midi.sh ten_bai --convert --bpm 90"
  exit 1
fi

BASE="$1"
shift

BASE="$(basename "$BASE" .mid)"
BASE="$(basename "$BASE" .midi)"

CONVERT=0
CONVERT_ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --convert)
      CONVERT=1
      shift
      ;;
    *)
      CONVERT_ARGS+=("$1")
      shift
      ;;
  esac
done

mkdir -p parts input

python3 merge_midi.py "$BASE" -i parts -o "input/${BASE}_gop.mid"

OUT="input/${BASE}_gop.mid"
if [ ! -f "$OUT" ]; then
  echo "Không tạo được: $OUT"
  exit 1
fi

if [ "$CONVERT" -eq 1 ]; then
  ./convert.sh "$OUT" "${CONVERT_ARGS[@]}"
fi
