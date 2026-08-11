#!/usr/bin/env python3
"""
MIDI → Ghost Story Piano MML.

Logic convert theo kiểu 3MLE / MabiIcco (mmlTools MidiFile.java):
  - Đổi tick MIDI → lưới TPQN=96 · encode 1/64 (32/64 + chấm)
  - Track A = giai điệu mono (nốt cao nhất mỗi thời điểm)
  - Track B / C = voice hòa âm / bass (tách nốt chồng)
  - Encode MML (t/v/o/l/<>/&/.) · l mặc định khi chuỗi cùng length

Dùng:
  python3 midi_to_ghoststory.py bai.mid
  python3 midi_to_ghoststory.py bai.mid -o output/ten_bai --limit 3000
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

try:
    from mido import MidiFile
except ImportError:
    sys.exit("Thiếu thư viện. Chạy: pip3 install mido")


# MabiIcco MMLTickTable.TPQN
TPQN = 96
# 1/64 = TPQN*4/64 = 6 — lưới encode chi tiết (giống MabiIcco / bản Cause I Love You)
MIN_TICK = 6
GRID = MIN_TICK

NOTE_NAMES = ["c", "c+", "d", "d+", "e", "f", "f+", "g", "g+", "a", "a+", "b"]


def _len_ticks(n: int, dotted: bool = False) -> int:
    t = (TPQN * 4) // n
    return t + t // 2 if dotted else t


# 1/1 … 1/64 (+ chấm) — chi tiết như MabiIcco export
LEN_PREFER = [
    (1, False),
    (2, True),
    (2, False),
    (4, True),
    (4, False),
    (8, True),
    (8, False),
    (16, True),
    (16, False),
    (32, True),
    (32, False),
    (64, True),
    (64, False),
]


def quantize(tick: int, grid: int = GRID) -> int:
    """Làm tròn về lưới 1/64 (hoặc grid tùy chọn)."""
    return int(round(tick / grid) * grid)


def safe_name(name: str) -> str:
    name = re.sub(r"[^\w\-]+", "_", name.strip(), flags=re.UNICODE)
    name = re.sub(r"_+", "_", name).strip("_").lower()
    return name or "bai_hat"


def conv_tick(tick: int, resolution: int) -> int:
    """MIDI tick → MML tick (TPQN=96), làm tròn MIN_TICK — như MabiIcco convTick."""
    value = int(tick * TPQN / resolution + MIN_TICK / 2)
    value -= value % MIN_TICK
    return max(0, value)


def parse_midi(path: str):
    """Đọc toàn bộ nốt (bỏ drum ch9). Trả về (notes, bpm, length_sec, resolution)."""
    mid = MidiFile(path)
    resolution = mid.ticks_per_beat

    bpm = 120
    for track in mid.tracks:
        for msg in track:
            if msg.type == "set_tempo":
                bpm = round(60_000_000 / msg.tempo)
                break
        else:
            continue
        break

    notes: list[dict] = []
    for track in mid.tracks:
        t = 0
        active: dict[tuple[int, int], tuple[int, int]] = {}
        for msg in track:
            t += msg.time
            if msg.type == "note_on" and msg.velocity > 0:
                if msg.channel == 9:
                    continue
                key = (msg.channel, msg.note)
                active[key] = (t, msg.velocity)
            elif msg.type == "note_off" or (
                msg.type == "note_on" and msg.velocity == 0
            ):
                if msg.channel == 9:
                    continue
                key = (msg.channel, msg.note)
                if key not in active:
                    continue
                start, vel = active.pop(key)
                start_m = conv_tick(start, resolution)
                end_m = conv_tick(t, resolution)
                dur = max(MIN_TICK, end_m - start_m)
                # Ghost Story: giữ pitch MIDI chuẩn (C4=60), không −12 như Mabinogi
                notes.append(
                    {
                        "start": start_m,
                        "dur": dur,
                        "end": start_m + dur,
                        "note": msg.note,
                        "vel": max(1, min(15, vel // 8)),
                    }
                )
    notes.sort(key=lambda n: (n["start"], n["note"]))
    return notes, bpm, mid.length, resolution


def overlaps(a: dict, b: dict) -> bool:
    """Hai nốt chồng thời gian (như MMLEventList.isOverlapNote)."""
    return a["start"] < b["end"] and b["start"] < a["end"]


def split_voices(notes: list[dict]) -> list[list[dict]]:
    """
    Tách nốt chồng → nhiều voice mono (greedy first-fit — MabiIcco createMMLEventList).
    Voice 0 nhận nốt đầu; nốt chồng sang voice kế.
    """
    voices: list[list[dict]] = []
    for note in notes:
        # bỏ nốt ngoài tầm piano game ~C1–C8
        if not (24 <= note["note"] <= 96):
            continue
        placed = False
        for voice in voices:
            if any(overlaps(note, existing) for existing in voice):
                continue
            # cắt nốt trước nếu kéo vào nốt mới (như addMMLNoteEvent)
            for prev in voice:
                if prev["start"] <= note["start"] < prev["end"]:
                    prev["dur"] = note["start"] - prev["start"]
                    prev["end"] = note["start"]
            voice[:] = [n for n in voice if n["dur"] >= MIN_TICK]
            voice.append(note.copy())
            voice.sort(key=lambda n: n["start"])
            placed = True
            break
        if not placed:
            voices.append([note.copy()])
    return voices


def ticks_to_mml_parts(ticks: int) -> list[str]:
    """Phân tick thành các length token (1, 2, 4., 8, 16, 32, 64 …)."""
    rem = ticks
    parts: list[str] = []
    whole_dot = _len_ticks(1, True)
    whole = _len_ticks(1, False)
    while rem > whole * 2:
        parts.append("1.")
        rem -= whole_dot

    while rem > 0:
        best = None
        for n, dotted in LEN_PREFER:
            t = _len_ticks(n, dotted)
            if t <= rem:
                tok = f"{n}." if dotted else str(n)
                best = (t, tok)
                break
        if best is None:
            break
        t, tok = best
        parts.append(tok)
        rem -= t
    return parts


def single_len_token(ticks: int) -> str | None:
    """Trả về token length nếu ticks khớp đúng 1 độ dài (vd '16', '8.'); else None."""
    for n, dotted in LEN_PREFER:
        if _len_ticks(n, dotted) == ticks:
            return f"{n}." if dotted else str(n)
    return None


def emit_length(name: str, ticks: int, tie: bool = True, default_l: str | None = None) -> str:
    """
    Emit note/rest với length.
    Nếu default_l khớp độ dài đơn → chỉ ghi tên nốt (như l16adfadf…).
    """
    parts = ticks_to_mml_parts(ticks)
    if not parts:
        return ""
    if (
        tie
        and len(parts) == 1
        and default_l is not None
        and parts[0] == default_l
        and name != "r"
    ):
        return name
    if tie and len(parts) > 1:
        return "&".join(name + p for p in parts)
    if tie:
        return name + parts[0]
    # rest: không dùng &; rest cũng hưởng default l nếu khớp
    if len(parts) == 1 and default_l is not None and parts[0] == default_l:
        return name
    return "".join(name + p for p in parts)


def encode_voice(notes: list[dict], bpm: int, vol: int, limit: int) -> str:
    """Encode 1 voice mono → MML Ghost Story chi tiết (lưới 1/64 + l mặc định)."""
    if not notes:
        return ""
    # Quantize start/dur về 1/64; gộp nốt liền cùng pitch
    qnotes: list[dict] = []
    for n in sorted(notes, key=lambda x: x["start"]):
        start = quantize(n["start"])
        end = max(start + GRID, quantize(n["start"] + n["dur"]))
        if qnotes and qnotes[-1]["note"] == n["note"] and qnotes[-1]["end"] >= start:
            qnotes[-1]["end"] = max(qnotes[-1]["end"], end)
            qnotes[-1]["dur"] = qnotes[-1]["end"] - qnotes[-1]["start"]
            continue
        if qnotes and start < qnotes[-1]["end"] and qnotes[-1]["note"] != n["note"]:
            qnotes[-1]["end"] = start
            qnotes[-1]["dur"] = start - qnotes[-1]["start"]
            if qnotes[-1]["dur"] < GRID:
                qnotes.pop()
        qnotes.append(
            {"start": start, "end": end, "dur": end - start, "note": n["note"]}
        )
    qnotes = [n for n in qnotes if n["dur"] >= GRID]
    if not qnotes:
        return ""

    def note_oct(midi: int) -> tuple[str, int]:
        midi = max(24, min(96, midi))
        return NOTE_NAMES[midi % 12], midi // 12 - 1

    # Octave tuyệt đối lúc đầu (oN) — giống bản Cause I Love You
    _, start_oct = note_oct(qnotes[0]["note"])
    out = f"t{bpm}v{vol}o{start_oct}"
    cur_oct = start_oct
    cursor = 0
    default_l: str | None = None

    def count_same_dur(from_i: int, dur: int) -> int:
        """Đếm nốt liên tiếp cùng độ dài (cho phép gap ≤ 1/64)."""
        cnt = 0
        prev_end = qnotes[from_i]["start"]
        for j in range(from_i, len(qnotes)):
            gap = qnotes[j]["start"] - prev_end
            if gap > GRID:
                break
            if qnotes[j]["dur"] != dur:
                break
            cnt += 1
            prev_end = qnotes[j]["end"]
        return cnt

    for i, n in enumerate(qnotes):
        chunk = ""
        gap = n["start"] - cursor
        if gap >= GRID:
            chunk += emit_length("r", gap, tie=False, default_l=default_l)

        name, octv = note_oct(n["note"])
        while cur_oct < octv:
            chunk += ">"
            cur_oct += 1
        while cur_oct > octv:
            chunk += "<"
            cur_oct -= 1

        tok = single_len_token(n["dur"])
        # Chuỗi ≥3 nốt cùng length → đặt lN rồi ghi tên trần (l16adfadf…)
        if tok and count_same_dur(i, n["dur"]) >= 3 and default_l != tok:
            chunk += f"l{tok}"
            default_l = tok
            chunk += name
        else:
            chunk += emit_length(name, n["dur"], tie=True, default_l=default_l)

        if len(out) + len(chunk) >= limit:
            break
        out += chunk
        cursor = max(cursor, n["end"])

    return out


def pick_three_voices(voices: list[list[dict]]) -> list[list[dict]]:
    """
    Lấy tối đa 3 voice (cao → thấp) để chọn B/C.
    Ưu tiên: nhiều nốt + phủ thời gian dài.
    """
    if not voices:
        return []

    def score(v: list[dict]) -> tuple:
        if not v:
            return (0, 0, 0)
        span = max(n["end"] for n in v) - min(n["start"] for n in v)
        avg_pitch = sum(n["note"] for n in v) / len(v)
        return (len(v), span, avg_pitch)

    ranked = sorted(voices, key=score, reverse=True)[:3]
    ranked.sort(key=lambda v: -(sum(n["note"] for n in v) / len(v)))
    return ranked


def to_mono_melody(notes: list[dict]) -> list[dict]:
    """Track A: cùng lúc nhiều nốt → giữ nốt cao nhất (giai điệu)."""
    by_start: dict[int, list[dict]] = {}
    for n in notes:
        if not (24 <= n["note"] <= 96):
            continue
        by_start.setdefault(n["start"], []).append(n)
    mono = []
    for start in sorted(by_start):
        best = max(by_start[start], key=lambda x: (x["note"], x.get("vel", 0)))
        mono.append(best.copy())
    for i in range(len(mono) - 1):
        if mono[i]["end"] > mono[i + 1]["start"]:
            mono[i]["end"] = mono[i + 1]["start"]
            mono[i]["dur"] = max(MIN_TICK, mono[i]["end"] - mono[i]["start"])
    return [n for n in mono if n["dur"] >= MIN_TICK]


def convert_to_folder(
    midi_path: str,
    out_dir: Path,
    bpm=None,
    vol: int = 15,
    limit: int = 3000,
    channel: int = -1,
    grid: int = 4,  # giữ arg cũ cho convert.sh; không dùng (logic tick TPQN)
):
    notes, detected_bpm, length_sec, _res = parse_midi(midi_path)
    use_bpm = bpm or detected_bpm or 90

    if channel >= 0:
        mid = MidiFile(midi_path)
        filtered = []
        for track in mid.tracks:
            t = 0
            active = {}
            for msg in track:
                t += msg.time
                if not hasattr(msg, "channel"):
                    continue
                if msg.channel != channel:
                    continue
                if msg.type == "note_on" and msg.velocity > 0:
                    active[msg.note] = (t, msg.velocity)
                elif msg.type == "note_off" or (
                    msg.type == "note_on" and msg.velocity == 0
                ):
                    if msg.note in active:
                        start, vel = active.pop(msg.note)
                        start_m = conv_tick(start, mid.ticks_per_beat)
                        end_m = conv_tick(t, mid.ticks_per_beat)
                        filtered.append(
                            {
                                "start": start_m,
                                "dur": max(MIN_TICK, end_m - start_m),
                                "end": start_m + max(MIN_TICK, end_m - start_m),
                                "note": msg.note,
                                "vel": max(1, min(15, vel // 8)),
                            }
                        )
        notes = sorted(filtered, key=lambda n: (n["start"], n["note"]))

    voices = split_voices(notes) if notes else []
    ranked = pick_three_voices(voices)
    # A = mono; B/C = voice thứ 2 / 3 (bỏ voice cao trùng giai điệu)
    mono_notes = to_mono_melody(notes)
    track_notes = [
        mono_notes,
        ranked[1] if len(ranked) > 1 else [],
        ranked[2] if len(ranked) > 2 else [],
    ]

    out_dir.mkdir(parents=True, exist_ok=True)

    for pattern in ("track_*.txt", "track_*.ghost.txt", "gop_*.txt", "gop_*.mml.txt"):
        for old in out_dir.glob(pattern):
            old.unlink()

    labels = [
        ("A", "track_A_single.ghost.txt", "giai điệu mono"),
        ("B", "track_B_harmony.ghost.txt", "hòa âm"),
        ("C", "track_C_bass.ghost.txt", "bass"),
    ]
    files = []
    lines = []
    codes = ["", "", ""]

    for i, (tag, fname, desc) in enumerate(labels):
        ns = track_notes[i]
        if not ns:
            continue
        code = encode_voice(ns, use_bpm, vol, limit)
        codes[i] = code
        (out_dir / fname).write_text(code + "\n", encoding="utf-8")
        files.append(fname)
        avg = sum(n["note"] for n in ns) / len(ns)
        lines.append(
            f"- {fname}  ({len(code)}/{limit}) — Track {tag} ({desc}, ~pitch {avg:.0f}, {len(ns)} nốt)"
        )

    used = sum(1 for c in codes if c)
    if len(voices) > 3:
        lines.append(
            f"- MIDI có {len(voices)} voice; B/C lấy từ top voice (bỏ {len(voices) - 3})"
        )
    elif used < 3 and len(voices) < 3:
        lines.append(f"- Chỉ tách được {used} track (MIDI ít chồng nốt)")

    # Bản ghép 1 dòng: MML@T..TrackA...,T..TrackB...,T..TrackC...;
    mml_parts = []
    for code in codes:
        if not code:
            continue
        # MML@ dùng T (hoa) thay vì t
        part = "T" + code[1:] if code.startswith("t") else code
        mml_parts.append(part)
    if mml_parts:
        gop_name = "gop_ABC.mml.txt"
        gop = "MML@" + ",".join(mml_parts) + ";\n"
        (out_dir / gop_name).write_text(gop, encoding="utf-8")
        files.append(gop_name)
        lines.append(f"- {gop_name}  — ghép A/B/C dạng MML@…;")

    song = out_dir.name
    file_list = "\n".join(lines) if lines else "- (không có nốt)"
    readme = f"""# {song} → Ghost Story Piano

Nguồn: {Path(midi_path).name}
BPM: {use_bpm}
Độ dài MIDI: {length_sec:.1f}s
Engine: MabiIcco-style · A single + B harmony + C bass
Voices nguồn: {len(voices)}

## File
{file_list}

## Cách dùng
1. track_A_single.ghost.txt → Track A
2. track_B_harmony.ghost.txt → Track B
3. track_C_bass.ghost.txt → Track C
4. gop_ABC.mml.txt → copy cả khối MML@A,B,C; (nếu tool/player hỗ trợ)
5. Tốc độ âm thanh ≈ {use_bpm}

## Ghi chú
- A = giai điệu mono · B = hòa âm · C = bass
- Format: MML chi tiết (t/v/o/l/<>/&/. · 1/64) · tối đa {limit} ký tự / track
- gop_ABC.mml.txt = MML@T…A…,T…B…,T…C…;
"""
    (out_dir / "README.txt").write_text(readme, encoding="utf-8")
    files.append("README.txt")

    return {
        "out_dir": str(out_dir),
        "bpm": use_bpm,
        "chars_a": len(codes[0]),
        "chars_b": len(codes[1]),
        "chars_c": len(codes[2]),
        "files": files,
        "limit": limit,
        "length_sec": round(length_sec, 1),
        "voices": len(voices),
        "used": used,
    }


def main():
    ap = argparse.ArgumentParser(
        description="MIDI → Ghost Story (logic kiểu 3MLE/MabiIcco)"
    )
    ap.add_argument("midi", help="File .mid")
    ap.add_argument("-o", "--out", default="", help="Folder output")
    ap.add_argument("--bpm", type=int, default=0)
    ap.add_argument("--vol", type=int, default=15)
    ap.add_argument("--limit", type=int, default=3000)
    ap.add_argument("--channel", type=int, default=-1, help="Chỉ lấy 1 MIDI channel")
    ap.add_argument(
        "--grid",
        type=int,
        default=4,
        help="(bỏ qua — giữ tương thích convert.sh; dùng TPQN=96)",
    )
    ap.add_argument("--print", dest="do_print", action="store_true")
    args = ap.parse_args()

    midi_path = Path(args.midi).expanduser()
    if not midi_path.exists():
        sys.exit(f"Không thấy file: {midi_path}")

    out_dir = (
        Path(args.out).expanduser()
        if args.out
        else Path("output") / safe_name(midi_path.stem)
    )

    meta = convert_to_folder(
        str(midi_path),
        out_dir,
        bpm=args.bpm or None,
        vol=args.vol,
        limit=args.limit,
        channel=args.channel,
        grid=args.grid,
    )

    print(f"OK → {meta['out_dir']}/")
    for f in meta["files"]:
        print(f"  - {f}")
    parts = [f"BPM {meta['bpm']}", f"ABC {meta['used']}/{meta['voices']}"]
    for tag, key in (("A", "chars_a"), ("B", "chars_b"), ("C", "chars_c")):
        if meta[key]:
            parts.append(f"{tag} {meta[key]}")
    print("  " + " | ".join(parts))
    if any(meta[k] >= meta["limit"] for k in ("chars_a", "chars_b", "chars_c")):
        print("  (một track đã cắt vì chạm giới hạn ký tự)")

    if args.do_print:
        print()
        print(
            (out_dir / "track_A_single.ghost.txt").read_text(encoding="utf-8").strip()
        )


if __name__ == "__main__":
    main()
