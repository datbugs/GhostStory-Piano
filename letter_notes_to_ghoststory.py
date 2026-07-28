#!/usr/bin/env python3
"""
Piano Letter Notes → mã Ghost Story.

Cách lấy letter notes:
  - Google: "<tên bài> piano letter notes"
  - Copy khối RH:5|...|  (và RH:4|...| nếu có) vào file .txt

Dùng:
  python3 letter_notes_to_ghoststory.py input/letter_notes/cause.txt
  python3 letter_notes_to_ghoststory.py input/letter_notes/cause.txt --bpm 90 --key Am

Mỗi lần chạy tạo:
  output/<ten>/
    track_A_ghoststory.txt
    README.txt
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

NOTE_MAP = {
    "a": ("a", 0),
    "A": ("a", 1),
    "b": ("b", 0),
    "B": ("b", 1),
    "c": ("c", 0),
    "C": ("c", 1),
    "d": ("d", 0),
    "D": ("d", 1),
    "e": ("e", 0),
    "E": ("e", 1),
    "f": ("f", 0),
    "F": ("f", 1),
    "g": ("g", 0),
    "G": ("g", 1),
}
NOTE_NAMES = ["c", "c+", "d", "d+", "e", "f", "f+", "g", "g+", "a", "a+", "b"]
LEN_NUM = {1: "16", 2: "8", 4: "4", 8: "2", 16: "1"}
DOTTED = {3: "8.", 6: "4.", 12: "2.", 24: "1."}


def midi_from(letter: str, octave: int) -> int:
    name, sharp = NOTE_MAP[letter]
    base = {"c": 0, "d": 2, "e": 4, "f": 5, "g": 7, "a": 9, "b": 11}[name]
    return (octave + 1) * 12 + base + sharp


def extract_note_blocks(text: str) -> list[list[tuple[int, str]]]:
    """Parse octave lines into blocks (paste 4|...| / pianoletternotes)."""
    note_line = re.compile(r"^(\d)\|([^|\n]*)\|?\s*$")
    blocks: list[list[tuple[int, str]]] = []
    cur: list[tuple[int, str]] = []
    blank = 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            blank += 1
            if blank >= 2 and cur:
                blocks.append(cur)
                cur = []
            continue
        m = note_line.match(line)
        if not m:
            continue  # bỏ số ô nhịp 1,2,3...
        octv, data = int(m.group(1)), m.group(2)
        if cur and (blank >= 1 or octv > cur[-1][0]):
            blocks.append(cur)
            cur = []
        blank = 0
        cur.append((octv, data))
    if cur:
        blocks.append(cur)
    return blocks


def blocks_to_rh(blocks: list[list[tuple[int, str]]], min_oct: int = 4) -> str:
    parts = []
    for block in blocks:
        rows = [f"RH:{octv}|{data}|" for octv, data in block if octv >= min_oct]
        if rows:
            parts.append("\n".join(rows))
    return "\n\n".join(parts)


def normalize_octave_paste(text: str, min_oct: int = 4) -> str:
    """Convert paste 4|G-G--| (+ số ô nhịp) → RH:4|...|"""
    if re.search(r"^RH:\d\|", text, re.M):
        return text
    if not re.search(r"^\d\|", text, re.M):
        return text
    blocks = extract_note_blocks(text)
    rh = blocks_to_rh(blocks, min_oct=min_oct)
    if not rh.strip():
        return text
    headers = [l for l in text.splitlines() if l.strip().startswith("#")]
    return ("\n".join(headers) + "\n\n" + rh + "\n") if headers else rh + "\n"


def parse_letter_notes(text: str):
    """Parse RH / octave paste into 16th-note slot stream (highest pitch per column)."""
    text = normalize_octave_paste(text)
    blocks, cur = [], []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            if cur:
                blocks.append(cur)
                cur = []
            continue
        if re.match(r"RH:\d\|", line):
            cur.append(line)
    if cur:
        blocks.append(cur)

    events = []
    for lines in blocks:
        rows = []
        for line in lines:
            m = re.match(r"RH:(\d)\|([^|]*)\|?", line)
            if not m:
                continue
            rows.append((int(m.group(1)), m.group(2)))
        if not rows:
            continue
        maxlen = max(len(r[1]) for r in rows)
        for i in range(maxlen):
            pitches = []
            for octv, data in rows:
                data = data.ljust(maxlen, "-")
                ch = data[i]
                if ch in NOTE_MAP:
                    pitches.append(midi_from(ch, octv))
            events.append(max(pitches) if pitches else None)
    return events


def encode_ghost(events, bpm=90, vol=15, limit=3000, start_oct=4) -> str:
    runs = []
    for ev in events:
        if ev is None and runs and runs[-1][0] is None:
            runs[-1] = (None, runs[-1][1] + 1)
        else:
            runs.append((ev, 1))

    out = f"t{bpm}v{vol}"
    cur_oct = start_oct
    default = None

    def pname(midi):
        midi = max(24, min(96, midi))
        return NOTE_NAMES[midi % 12], midi // 12 - 1

    def rest(n):
        s, rem = "", n
        for p, tok in [
            (16, "r1"),
            (12, "r2."),
            (8, "r2"),
            (6, "r4."),
            (4, "r4"),
            (3, "r8."),
            (2, "r8"),
            (1, "r16"),
        ]:
            while rem >= p:
                s += tok
                rem -= p
        return s

    i = 0
    while i < len(runs):
        pitch, n16 = runs[i]
        chunk = ""
        if pitch is None:
            chunk = rest(n16)
        else:
            name, octv = pname(pitch)
            while cur_oct < octv:
                chunk += ">"
                cur_oct += 1
            while cur_oct > octv:
                chunk += "<"
                cur_oct -= 1
            if n16 == 1:
                if default != 1:
                    chunk += "l16"
                    default = 1
                chunk += name
            elif n16 == 2:
                if default != 2:
                    nxt = sum(
                        1
                        for j in range(i, min(i + 5, len(runs)))
                        if runs[j][0] is not None and runs[j][1] == 2
                    )
                    if nxt >= 3:
                        chunk += "l8"
                        default = 2
                        chunk += name
                    else:
                        chunk += name + "8"
                else:
                    chunk += name
            elif n16 in DOTTED:
                chunk += name + DOTTED[n16]
            elif n16 in LEN_NUM:
                chunk += name + LEN_NUM[n16]
            else:
                rem, first, s = n16, True, ""
                for p, tok in [
                    (16, "1"),
                    (12, "2."),
                    (8, "2"),
                    (6, "4."),
                    (4, "4"),
                    (3, "8."),
                    (2, "8"),
                    (1, "16"),
                ]:
                    while rem >= p:
                        if not first:
                            s += "&"
                        s += name if (p == 1 and default == 1 and first) else name + tok
                        rem -= p
                        first = False
                chunk += s

        if len(out) + len(chunk) > limit:
            break
        out += chunk
        m = re.search(r"l(16|8|4|2|1)", chunk)
        if m:
            default = {"16": 1, "8": 2, "4": 4, "2": 8, "1": 16}[m.group(1)]
        i += 1
    return out


def safe_name(name: str) -> str:
    name = re.sub(r"[^\w\-]+", "_", name.strip(), flags=re.UNICODE)
    return re.sub(r"_+", "_", name).strip("_").lower() or "bai_hat"


def extract_meta_from_text(text: str):
    """Optional header in file:
    # title: Cause I Love You
    # key: Am
    # bpm: 90
    # chords: F G Em Am E7
    """
    meta = {"title": "", "key": "", "bpm": 0, "chords": "", "style": ""}
    for line in text.splitlines():
        m = re.match(r"#\s*(title|key|bpm|chords|style)\s*:\s*(.+)$", line.strip(), re.I)
        if m:
            k = m.group(1).lower()
            v = m.group(2).strip()
            if k == "bpm":
                try:
                    meta["bpm"] = int(re.findall(r"\d+", v)[0])
                except Exception:
                    pass
            else:
                meta[k] = v
    return meta


def main():
    ap = argparse.ArgumentParser(description="Letter notes → Ghost Story")
    ap.add_argument("input", help="File .txt chứa 4|...| hoặc RH:5|...|")
    ap.add_argument("-o", "--out", default="")
    ap.add_argument("--bpm", type=int, default=0)
    ap.add_argument("--vol", type=int, default=15)
    ap.add_argument("--limit", type=int, default=3000)
    ap.add_argument("--key", default="")
    ap.add_argument("--title", default="")
    ap.add_argument("--min-oct", type=int, default=4, help="Chỉ lấy octave >= N (mặc định 4)")
    args = ap.parse_args()

    src = Path(args.input).expanduser()
    if not src.exists():
        sys.exit(f"Không thấy: {src}")

    text = src.read_text(encoding="utf-8")
    # apply min-oct for octave paste
    if re.search(r"^\d\|", text, re.M) and not re.search(r"^RH:\d\|", text, re.M):
        text = normalize_octave_paste(text, min_oct=args.min_oct)
    file_meta = extract_meta_from_text(text)
    events = parse_letter_notes(text)
    if not events:
        sys.exit(
            "Không tìm thấy letter notes.\n"
            "Hỗ trợ: paste 4|G-G--|  hoặc  RH:5|...|"
        )

    bpm = args.bpm or file_meta["bpm"] or 90
    title = args.title or file_meta["title"] or src.stem
    key = args.key or file_meta["key"]

    code = encode_ghost(events, bpm=bpm, vol=args.vol, limit=args.limit)
    out_dir = Path(args.out) if args.out else Path("output") / safe_name(title)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "track_A_ghoststory.txt").write_text(code + "\n", encoding="utf-8")

    readme = f"""# {title} → Ghost Story Piano

Nguồn: Letter notes
File gốc: {src.name}
BPM: {bpm}
Tông: {key or "(không khai báo)"}

## File
- track_A_ghoststory.txt  ({len(code)}/{args.limit} ký tự)

## Cách dùng
1. Copy toàn bộ track_A_ghoststory.txt
2. Ghost Story → Track A → dán
3. Tốc độ ≈ {bpm}
"""
    (out_dir / "README.txt").write_text(readme, encoding="utf-8")
    (out_dir / "source_letter_notes.txt").write_text(
        src.read_text(encoding="utf-8"), encoding="utf-8"
    )

    print(f"OK → {out_dir}/")
    print("  - track_A_ghoststory.txt")
    print("  - README.txt")
    print("  - source_letter_notes.txt")
    print(f"  Track A: {len(code)}/{args.limit} ký tự | BPM {bpm}" + (f" | Key {key}" if key else ""))


if __name__ == "__main__":
    main()
