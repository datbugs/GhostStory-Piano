#!/usr/bin/env python3
"""
MIDI → Ghost Story Piano MML.

Logic convert theo kiểu 3MLE / MabiIcco (mmlTools MidiFile.java):
  - Đổi tick MIDI → lưới TPQN=96
  - Nốt chồng nhau → tách sang voice mới (giữ hợp âm qua Track A/B/C)
  - Mỗi voice là mono → encode MML (t/v/<>/&/.)
  - Tối đa 3 voice → Track A / B / C

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
# 1/64 nội bộ (parse), rồi quantize về 1/16 khi encode (Ghost Story ổn định hơn)
MIN_TICK = 6
# 1/16 note = TPQN * 4 / 16 = 24 — độ phân giải encode cho game
GRID_16 = 24

NOTE_NAMES = ["c", "c+", "d", "d+", "e", "f", "f+", "g", "g+", "a", "a+", "b"]


def _len_ticks(n: int, dotted: bool = False) -> int:
    t = (TPQN * 4) // n
    return t + t // 2 if dotted else t


# Ghost Story: chỉ dùng 1/1 … 1/16 (+ chấm) — tránh 32/64
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
]


def quantize_16(tick: int) -> int:
    """Làm tròn về lưới 1/16."""
    return int(round(tick / GRID_16) * GRID_16)


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
    """Phân tick thành các length token (1, 2, 4., 8, …)."""
    rem = ticks
    parts: list[str] = []
    # Nuốt nốt trắng chấm nếu rất dài
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
            # không khớp — bỏ phần dư nhỏ
            break
        t, tok = best
        parts.append(tok)
        rem -= t
    return parts


def emit_length(name: str, ticks: int, tie: bool = True) -> str:
    parts = ticks_to_mml_parts(ticks)
    if not parts:
        return ""
    if tie and len(parts) > 1:
        return "&".join(name + p for p in parts)
    if tie:
        return name + parts[0]
    # rest: không dùng &
    return "".join(name + p for p in parts)


def encode_voice(notes: list[dict], bpm: int, vol: int, limit: int) -> str:
    """Encode 1 voice mono → MML Ghost Story (lưới 1/16)."""
    if not notes:
        return ""
    # Quantize start/dur về 1/16; gộp nốt liền cùng pitch
    qnotes: list[dict] = []
    for n in sorted(notes, key=lambda x: x["start"]):
        start = quantize_16(n["start"])
        end = max(start + GRID_16, quantize_16(n["start"] + n["dur"]))
        if qnotes and qnotes[-1]["note"] == n["note"] and qnotes[-1]["end"] >= start:
            qnotes[-1]["end"] = max(qnotes[-1]["end"], end)
            qnotes[-1]["dur"] = qnotes[-1]["end"] - qnotes[-1]["start"]
            continue
        if qnotes and start < qnotes[-1]["end"] and qnotes[-1]["note"] != n["note"]:
            # cắt nốt trước cho khớp lưới
            qnotes[-1]["end"] = start
            qnotes[-1]["dur"] = start - qnotes[-1]["start"]
            if qnotes[-1]["dur"] < GRID_16:
                qnotes.pop()
        qnotes.append(
            {"start": start, "end": end, "dur": end - start, "note": n["note"]}
        )
    qnotes = [n for n in qnotes if n["dur"] >= GRID_16]
    if not qnotes:
        return ""

    out = f"t{bpm}v{vol}"
    cur_oct = 4
    cursor = 0

    def note_oct(midi: int) -> tuple[str, int]:
        midi = max(24, min(96, midi))
        return NOTE_NAMES[midi % 12], midi // 12 - 1

    for n in qnotes:
        chunk = ""
        gap = n["start"] - cursor
        if gap >= GRID_16:
            chunk += emit_length("r", gap, tie=False)

        name, octv = note_oct(n["note"])
        while cur_oct < octv:
            chunk += ">"
            cur_oct += 1
        while cur_oct > octv:
            chunk += "<"
            cur_oct -= 1

        chunk += emit_length(name, n["dur"], tie=True)

        if len(out) + len(chunk) > limit:
            break
        out += chunk
        cursor = max(cursor, n["end"])

    return out


def pick_three_voices(voices: list[list[dict]]) -> list[list[dict]]:
    """
    Lấy tối đa 3 voice cho Track A/B/C.
    Ưu tiên: nhiều nốt + phủ thời gian dài (giữ hợp âm chính).
    Giữ thứ tự: cao → thấp để A≈melody, C≈bass khi có thể.
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
    # Sắp lại theo pitch trung bình giảm dần: A cao, B giữa, C thấp
    ranked.sort(key=lambda v: -(sum(n["note"] for n in v) / len(v)))
    return ranked


def to_mono_melody(notes: list[dict]) -> list[dict]:
    """1 track: cùng lúc nhiều nốt → giữ nốt cao nhất (giai điệu)."""
    by_start: dict[int, list[dict]] = {}
    for n in notes:
        if not (24 <= n["note"] <= 96):
            continue
        by_start.setdefault(n["start"], []).append(n)
    mono = []
    for start in sorted(by_start):
        best = max(by_start[start], key=lambda x: (x["note"], x.get("vel", 0)))
        mono.append(best.copy())
    # cắt nếu nốt sau bắt đầu trước khi nốt trước kết thúc
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
    single: bool = False,
):
    notes, detected_bpm, length_sec, _res = parse_midi(midi_path)
    use_bpm = bpm or detected_bpm or 90

    if channel >= 0:
        # lọc 1 channel nếu user chỉ định (channel lưu không còn — parse lại)
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

    if single:
        # Chỉ tạo bản 1 kỹ năng; không xóa A/B/C có sẵn
        voices = [to_mono_melody(notes)] if notes else []
        chosen = []
    else:
        voices = split_voices(notes)
        chosen = pick_three_voices(voices)

    out_dir.mkdir(parents=True, exist_ok=True)

    if not single:
        # Convert đủ: xóa rồi ghi lại A/B/C + single + gop
        for old in out_dir.glob("track_*.txt"):
            old.unlink()
        for old in out_dir.glob("track_*.ghost.txt"):
            old.unlink()
        gop_old = out_dir / "gop_ABC.txt"
        if gop_old.exists():
            gop_old.unlink()

    files = []
    lines = []
    codes: list[str] = ["", "", ""]
    counts = [0, 0, 0]

    # —— Track A/B/C (thêm sau khi mở kỹ năng) ——
    labels = [
        ("A", "track_A_ghoststory.txt", "voice cao — thêm sau"),
        ("B", "track_B_harmony.ghost.txt", "hòa âm — thêm sau"),
        ("C", "track_C_bass.ghost.txt", "bass — thêm sau"),
    ]
    if not single:
        for i, (tag, fname, desc) in enumerate(labels):
            if i >= len(chosen):
                continue
            code = encode_voice(chosen[i], use_bpm, vol, limit)
            codes[i] = code
            counts[i] = len(chosen[i])
            (out_dir / fname).write_text(code + "\n", encoding="utf-8")
            files.append(fname)
            avg = sum(n["note"] for n in chosen[i]) / len(chosen[i])
            lines.append(
                f"- {fname}  ({len(code)}/{limit}) — Track {tag} ({desc}, ~pitch {avg:.0f}, {len(chosen[i])} nốt)"
            )

    # —— Bản 1 kỹ năng (giai điệu mono) ——
    mono_notes = to_mono_melody(notes)
    code_single = encode_voice(mono_notes, use_bpm, vol, limit) if mono_notes else ""
    single_name = "track_A_single.ghost.txt"
    if code_single:
        (out_dir / single_name).write_text(code_single + "\n", encoding="utf-8")
        files.append(single_name)
        lines.insert(
            0,
            f"- {single_name}  ({len(code_single)}/{limit}) — DÙNG NGAY (1 kỹ năng → dán Track A)",
        )

    # Bản ghộp A/B/C
    if not single and sum(1 for c in codes if c) >= 2:
        gop_name = "gop_ABC.txt"
        gop_parts = []
        for i, tag in enumerate("ABC"):
            if not codes[i]:
                continue
            gop_parts.append(f"===== TRACK {tag} (copy → Track {tag} trong game) =====")
            gop_parts.append(codes[i])
            gop_parts.append("")
        if gop_parts:
            (out_dir / gop_name).write_text(
                "\n".join(gop_parts).rstrip() + "\n", encoding="utf-8"
            )
            files.append(gop_name)
            lines.append(f"- {gop_name}  — bản ghộp A/B/C")

    if not single and len(chosen) < 2:
        lines.append(f"- Chỉ tách được {len(chosen)} voice (MIDI ít chồng nốt)")
    if not single and len(voices) > 3:
        lines.append(
            f"- MIDI có {len(voices)} voice; giữ 3 voice nhiều nốt nhất (bỏ {len(voices) - 3})"
        )

    n_voice = len(chosen) if not single else 0
    n_total = len(voices) if not single else 1
    song = out_dir.name
    file_list = "\n".join(lines) if lines else "- (không có nốt)"
    readme = f"""# {song} → Ghost Story Piano

Nguồn: {Path(midi_path).name}
BPM: {use_bpm}
Độ dài MIDI: {length_sec:.1f}s
Engine: MabiIcco-style + bản single
Voices ABC: {n_voice}/{n_total if not single else "—"}

## File
{file_list}

## Cách dùng
### Bây giờ (mới mở 1 kỹ năng)
1. Mở **track_A_single.ghost.txt** → Copy hết → dán **Track A**
2. Tốc độ âm thanh ≈ {use_bpm}

### Sau này (mở thêm kỹ năng Track B/C)
1. track_A_ghoststory.txt → Track A
2. track_B_harmony.ghost.txt → Track B
3. track_C_bass.ghost.txt → Track C
   (hoặc copy từng đoạn trong gop_ABC.txt)

## Ghi chú
- track_A_single = giai điệu mono (1 track)
- track_A/B/C = tách voice (hợp âm), thêm dần khi mở skill
- Format: MML Ghost Story (t/v/<>/&/.)
"""
    (out_dir / "README.txt").write_text(readme, encoding="utf-8")
    files.append("README.txt")

    return {
        "out_dir": str(out_dir),
        "bpm": use_bpm,
        "chars_a": len(codes[0]),
        "chars_b": len(codes[1]),
        "chars_c": len(codes[2]),
        "chars_single": len(code_single),
        "mel_ch": f"v0/{counts[0]}" if counts[0] else "n/a",
        "bass_ch": f"v2/{counts[2]}" if counts[2] else "n/a",
        "harm_ch": f"v1/{counts[1]}" if counts[1] else "n/a",
        "files": files,
        "limit": limit,
        "length_sec": round(length_sec, 1),
        "voices": n_total,
        "used": n_voice,
        "single": single,
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
        "--single",
        "-s",
        action="store_true",
        help="Chỉ ghi lại track_A_single (không đụng A/B/C đã có)",
    )
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
        single=args.single,
    )

    print(f"OK → {meta['out_dir']}/")
    for f in meta["files"]:
        print(f"  - {f}")
    parts = [f"BPM {meta['bpm']}", f"ABC {meta['used']}/{meta['voices']}"]
    if meta.get("chars_single"):
        parts.append(f"single {meta['chars_single']}")
    if meta["chars_a"]:
        parts.append(f"A {meta['chars_a']}")
    if meta["chars_b"]:
        parts.append(f"B {meta['chars_b']}")
    if meta["chars_c"]:
        parts.append(f"C {meta['chars_c']}")
    print("  " + " | ".join(parts))
    if meta.get("chars_single", 0) >= meta["limit"] or meta["chars_a"] >= meta["limit"]:
        print("  (một track đã cắt vì chạm giới hạn ký tự)")

    if args.do_print:
        print()
        sp = out_dir / "track_A_single.ghost.txt"
        apath = out_dir / "track_A_ghoststory.txt"
        target = sp if sp.exists() else apath
        print(target.read_text(encoding="utf-8").strip())


if __name__ == "__main__":
    main()
