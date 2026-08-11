#!/usr/bin/env python3
"""
Ghép nhiều file MIDI cùng bài (nối tiếp theo thời gian).

Phần lẻ đặt trong parts/: name.mid, name1.mid, name2.mid, ...
Ghép xong tự ghi ra input/<name>_gop.mid

Dùng:
  python3 merge_midi.py seeyouagain
  python3 merge_midi.py seeyouagain -i parts -o input/seeyouagain_gop.mid
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

try:
    from mido import Message, MetaMessage, MidiFile, MidiTrack
except ImportError:
    sys.exit("Thiếu thư viện. Chạy: pip3 install mido")


def find_parts(parts_dir: Path, base: str) -> list[Path]:
    """Tìm name.mid, name1.mid, name2.mid… (chỉ suffix số, không khớp tên dài hơn)."""
    # ưu tiên subfolder parts/<base>/ nếu có
    search_dirs = []
    sub = parts_dir / base
    if sub.is_dir():
        search_dirs.append(sub)
    search_dirs.append(parts_dir)

    found: list[tuple[int, Path]] = []
    seen: set[int] = set()
    for d in search_dirs:
        for p in d.iterdir():
            if not p.is_file():
                continue
            if p.suffix.lower() not in (".mid", ".midi"):
                continue
            stem = p.stem
            idx: int | None = None
            if stem == base:
                idx = 0
            else:
                m = re.fullmatch(re.escape(base) + r"(\d+)", stem)
                if m:
                    idx = int(m.group(1))
            if idx is None or idx in seen:
                continue
            seen.add(idx)
            found.append((idx, p))
    found.sort(key=lambda x: x[0])
    return [p for _, p in found]


def _scale_time(ticks: int, from_tpb: int, to_tpb: int) -> int:
    if from_tpb == to_tpb:
        return ticks
    return int(round(ticks * to_tpb / from_tpb))


def concatenate(paths: list[Path], out_path: Path) -> None:
    mids = [MidiFile(str(p)) for p in paths]
    base_tpb = mids[0].ticks_per_beat

    # (abs_tick, msg) — bỏ end_of_track; tempo chỉ giữ từ file đầu
    events: list[tuple[int, Message | MetaMessage]] = []
    offset = 0
    keep_tempo = True

    for mid in mids:
        file_events: list[tuple[int, Message | MetaMessage]] = []
        file_end = 0
        for track in mid.tracks:
            t = 0
            for msg in track:
                t += msg.time
                abs_t = _scale_time(t, mid.ticks_per_beat, base_tpb)
                file_end = max(file_end, abs_t)
                if msg.type == "end_of_track":
                    continue
                if msg.is_meta and msg.type == "set_tempo":
                    if not keep_tempo:
                        continue
                file_events.append((abs_t, msg.copy(time=0)))

        for abs_t, msg in file_events:
            events.append((abs_t + offset, msg))
        offset += file_end
        keep_tempo = False

    events.sort(key=lambda x: (x[0], 0 if x[1].is_meta else 1))

    out = MidiFile(ticks_per_beat=base_tpb)
    track = MidiTrack()
    out.tracks.append(track)

    prev = 0
    for abs_t, msg in events:
        delta = max(0, abs_t - prev)
        track.append(msg.copy(time=delta))
        prev = abs_t
    track.append(MetaMessage("end_of_track", time=0))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.save(str(out_path))


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Ghép MIDI từ parts/ → input/<name>_gop.mid"
    )
    ap.add_argument(
        "base",
        help="Tên gốc (vd: seeyouagain → tìm seeyouagain.mid, seeyouagain1.mid, ...)",
    )
    ap.add_argument(
        "-i",
        "--parts-dir",
        default="parts",
        help="Folder chứa phần lẻ (mặc định: parts)",
    )
    ap.add_argument(
        "-o",
        "--output",
        default=None,
        help="File output (mặc định: input/<base>_gop.mid)",
    )
    args = ap.parse_args()

    base = Path(args.base).name
    for ext in (".mid", ".midi", ".MID", ".MIDI"):
        if base.endswith(ext):
            base = base[: -len(ext)]
            break

    parts_dir = Path(args.parts_dir)
    if not parts_dir.is_dir():
        sys.exit(
            f"Không thấy folder: {parts_dir}/\n"
            f"Tạo folder và bỏ name.mid, name1.mid, ... vào đó."
        )

    parts = find_parts(parts_dir, base)
    if not parts:
        sys.exit(
            f"Không thấy file khớp '{base}.mid', '{base}1.mid', ... trong {parts_dir}/"
            f" (hoặc {parts_dir}/{base}/)"
        )
    if len(parts) == 1:
        print(f"Chỉ có 1 file: {parts[0]} — không cần ghép.")
        print(f"Đặt thêm: {base}1.mid, {base}2.mid, ... vào {parts_dir}/")
        sys.exit(1)

    out_path = Path(args.output) if args.output else Path("input") / f"{base}_gop.mid"
    concatenate(parts, out_path)

    print(f"Đã ghép {len(parts)} file → {out_path}")
    for i, p in enumerate(parts):
        print(f"  {i + 1}. {p}")
    print("")
    print("Convert tiếp:")
    print(f"  ./convert.sh {out_path.name}")


if __name__ == "__main__":
    main()
