#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Аудит спеки skor-skeleton v1 (Rust-промт) и прототипы слоёв на 677647.fb2.

Часть 1: биективность их таблицы транслита (буквы, пары, тройки) + латиница.
Часть 2: V-marker — ASCII-транслит (исправленная биективная таблица) + маркер
         0x7F + токены слов + триграммы; roundtrip на всём файле.
Часть 3: V-byte — однобайтовые коды кириллицы + триграммы; roundtrip.
Часть 4: varint базы-1000 (10 бит на группу) для длинных чисел.
Часть 5: inline-равенства в FB2 + демо math-нормализации в прозе.
Запуск из этой папки: python3 -I skor_ideas_bench.py
"""
import json
import lzma
import os
import random
import re
import time

import zstandard as zstd

DIR = os.path.dirname(os.path.abspath(__file__))
FB2 = "/home/z/my-project/upload/677647.fb2"

# ═══════════════ Часть 1. Аудит их таблицы ═══════════════
SPEC_THEIR = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo",
    "ж": "zh", "з": "z", "и": "i", "й": "j", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch",
    "ъ": "", "ы": "y", "ь": "'", "э": "'e", "ю": "yu", "я": "ya",
}
OUT_TO_SRC = {v: k for k, v in SPEC_THEIR.items() if v}
OUT_TO_SRC["''"] = "'"
DEC_RE = re.compile("|".join(re.escape(o) for o in
                             sorted(OUT_TO_SRC, key=len, reverse=True)))


def dec_their(s):
    return DEC_RE.sub(lambda m: OUT_TO_SRC[m.group(0)], s)


def enc_their(s):
    return s.replace("'", "''").translate(str.maketrans(SPEC_THEIR))


fail_single = [c for c in SPEC_THEIR if dec_their(enc_their(c)) != c]
CYR = list(SPEC_THEIR)
fail_pairs = []
for a in CYR:
    for b in CYR:
        s = a + b
        if dec_their(enc_their(s)) != s:
            fail_pairs.append(f"{s}->{enc_their(s)}->{dec_their(enc_their(s))}")
fail_triples = []
for a in CYR:
    for b in CYR:
        for c in CYR:
            s = a + b + c
            if dec_their(enc_their(s)) != s:
                fail_triples.append(s)
latin_demo = {w: dec_their(w) for w in ("ship", "shot", "take", "children")}
print("=== 1. Аудит их таблицы ===")
print("Одиночные, битые:", fail_single)
print(f"Пары, битые: {len(fail_pairs)}", fail_pairs[:14])
print(f"Тройки, битые: {len(fail_triples)} (первые 10): {fail_triples[:10]}")
print("Их декодер на латинице:", latin_demo)

# Исправленная таблица (биективность проверяется кодом ниже):
# й->j, ъ->q, ы->w, ь->qh, э->eh, ц->c, щ->ysh; остальные — мнемонические.
SPEC_FIX = dict(SPEC_THEIR)
SPEC_FIX.update({"й": "j", "ъ": "q", "ы": "w", "ь": "qh", "э": "eh",
                 "ц": "c", "щ": "ysh"})
FIX_TO_SRC = {v: k for k, v in SPEC_FIX.items() if v}
FIX_TO_SRC_FULL = dict(FIX_TO_SRC)
for _k, _v in SPEC_FIX.items():
    if _v:
        FIX_TO_SRC_FULL[_v.upper() if len(_v) == 1 else _v[0].upper() + _v[1:]] = _k.upper()
FIX_DEC_RE = re.compile("|".join(re.escape(o) for o in
                                 sorted(FIX_TO_SRC, key=len, reverse=True)))


def enc_fix(s):
    return s.replace("'", "''").translate(str.maketrans(SPEC_FIX))


def dec_fix(s):
    return FIX_DEC_RE.sub(
        lambda m: "'" if m.group(0) == "''" else FIX_TO_SRC[m.group(0)], s)


fail_fix = []
for a in CYR:
    for b in CYR:
        for c in CYR:
            s = a + b + c
            if dec_fix(enc_fix(s)) != s:
                fail_fix.append(f"{s}->{enc_fix(s)}->{dec_fix(enc_fix(s))}")
print(f"Исправленная таблица: битых троек {len(fail_fix)}", fail_fix[:6])

TRANS_FIX = str.maketrans(
    {c: v for c, v in SPEC_FIX.items()} |
    {c.upper(): (v[0].upper() + v[1:]) if len(v) > 1 else v.upper()
     for c, v in SPEC_FIX.items()})
FIX_ALL_OUT = sorted(list(FIX_TO_SRC_FULL) + ["''"], key=len, reverse=True)
FIX_OUT_RE = re.compile("|".join(re.escape(o) for o in FIX_ALL_OUT))


def untranslit_word(s):
    return FIX_OUT_RE.sub(
        lambda m: "'" if m.group(0) == "''" else FIX_TO_SRC_FULL[m.group(0)], s)


def translit_word(w):
    return w.translate(TRANS_FIX)

# ═══════════════ Разбор FB2 на словные прогоны ═══════════════
t0 = time.perf_counter()
with open(FB2, "rb") as f:
    fb2_bytes = f.read()
text = fb2_bytes.decode("utf-8")
print(f"\nфайл: {len(fb2_bytes):,} Б, {len(text):,} символов, "
      f"чтение {time.perf_counter() - t0:.1f} с")

WORD_RE = re.compile(r"[A-Za-z]+|[А-Яа-яЁё]+")
runs, lits, prev = [], [], 0
for m in WORD_RE.finditer(text):
    lits.append(text[prev:m.start()])
    runs.append(m.group(0))
    prev = m.end()
lits.append(text[prev:])
n_cyr = sum(1 for w in runs if w[0].lower() in SPEC_THEIR)
n_latin = len(runs) - n_cyr
adj_cyr_latin = len(re.findall(r"[А-Яа-яЁё][A-Za-z]", text))
adj_latin_cyr = len(re.findall(r"[A-Za-z][А-Яа-яЁё]", text))
print(f"прогонов: {len(runs):,} (кириллических {n_cyr:,}, латинских {n_latin:,})")
print(f"смежные кириллица|латиница: {adj_cyr_latin:,} + {adj_latin_cyr:,}")

RAW_FULL_RE = re.compile(rb"[\x00-\x08\x0b-\x1f\x7f]|[^\x00-\x7f]+")


def wrap_all(data):
    """Заворачивает непечатаемые/не-ASCII байты в RAW-блоки FF+len+байты."""
    out, prev = [], 0
    for m in RAW_FULL_RE.finditer(data):
        out.append(data[prev:m.start()])
        frag = m.group(0)
        for i in range(0, len(frag), 255):
            chunk = frag[i:i + 255]
            out.append(b"\xff" + bytes([len(chunk)]) + chunk)
        prev = m.end()
    out.append(data[prev:])
    return b"".join(out)


def unwrap_raw(data):
    out = bytearray()
    i = lit = 0
    n = len(data)
    while i < n:
        if data[i] == 0xFF:
            out += data[lit:i]
            ln = data[i + 1]
            out += data[i + 2:i + 2 + ln]
            i += 2 + ln
            lit = i
        else:
            i += 1
    out += data[lit:]
    return bytes(out)

# ═══════════════ Общие таблицы слоёв 2-3 ═══════════════
EN_TRI = ["the", "ing", "and", "ion", "ent", "tio", "tha", "hat", "her",
          "ere", "ate", "for", "his", "con", "res", "ter"]
RU_TRI_CYR = ["ено", "ное", "сто", "ого", "его", "ние", "ает", "ете", "ест",
              "тво", "при", "ето", "как", "ный", "ова", "ени", "ост", "ите",
              "тог", "ани", "нов", "ств", "енн", "ует", "нно", "еже", "гда",
              "оно", "обо", "тот", "дел", "вет", "гор", "пра", "час", "тся"]
RU_TRI = [translit_word(g) for g in RU_TRI_CYR]   # написание v2 для V-marker
WORD_TOKENS = {w: 0x80 + i for i, w in enumerate(
    ["the", "and", "that", "with", "have", "not", "will", "from", "they",
     "would", "this", "been", "what", "when", "there", "more"])}
EN_TRI_RE = re.compile("|".join(map(re.escape, sorted(EN_TRI, key=len, reverse=True))))
RU_TRI_RE = re.compile("|".join(map(re.escape, sorted(RU_TRI, key=len, reverse=True))))
TOKEN_RE = re.compile("|".join(re.escape(w) for w in
                               sorted(WORD_TOKENS, key=len, reverse=True)))

# ═══════════════ Часть 2. V-marker ═══════════════
EN_CODE = {g: 0xC1 + i for i, g in enumerate(EN_TRI)}    # 0xC1..0xD0
RU_CODE = {g: 0xD1 + i for i, g in enumerate(RU_TRI)}    # 0xD1..0xF4
RU_TRI_B_RE = re.compile(b"|".join(re.escape(g.encode()) for g in
                                   sorted(RU_TRI, key=len, reverse=True)))
EN_TRI_B_RE = re.compile(b"|".join(re.escape(g.encode()) for g in
                                   sorted(EN_TRI, key=len, reverse=True)))
RU_CODE_INV = {bytes([c]): g for g, c in RU_CODE.items()}
EN_CODE_INV = {bytes([c]): g for g, c in EN_CODE.items()}
CODE_ANY_RE = re.compile(b"|".join(re.escape(c) for c in
                                   sorted(RU_CODE_INV | EN_CODE_INV)))


def encode_marker():
    parts = []
    for idx, (lit, run) in enumerate(zip(lits, runs)):
        if lit:
            parts.append(wrap_all(lit.encode("utf-8")))
        if run[0].lower() in SPEC_THEIR:
            inner = RU_TRI_B_RE.sub(
                lambda mm: bytes([RU_CODE[mm.group(0).decode("ascii")]]),
                translit_word(run).encode("ascii"))
            # терминатор нужен, только если впритык идёт латинский прогон
            # (декодер иначе проглотил бы его в помеченное слово)
            nxt = runs[idx + 1] if idx + 1 < len(runs) else ""
            term = b"\x00" if nxt and nxt[0].lower() not in SPEC_THEIR else b""
            parts.append(b"\x7f" + inner + term)
        else:
            if run in WORD_TOKENS:
                parts.append(bytes([WORD_TOKENS[run]]))
            else:
                parts.append(EN_TRI_B_RE.sub(
                    lambda mm: bytes([EN_CODE[mm.group(0).decode("ascii")]]),
                    run.encode("ascii")))
    parts.append(wrap_all(lits[-1].encode("utf-8")))
    return b"".join(parts)


def decode_marker(enc):
    """Ручной автомат: 0xFF -> RAW дословно, 0x7F -> помеченное слово,
    0x80-0x8F -> токен, 0xC1-0xD0 -> EN-триграмма, остальное -> литерал."""
    out = bytearray()
    lit = 0
    i = 0
    n = len(enc)
    while i < n:
        b = enc[i]
        if b == 0xFF:
            out += enc[lit:i]
            ln = enc[i + 1]
            out += enc[i + 2:i + 2 + ln]
            i += 2 + ln
            lit = i
            continue
        if b == 0x7F:
            out += enc[lit:i]
            j = i + 1
            while j < n and (0x41 <= enc[j] <= 0x5A or 0x61 <= enc[j] <= 0x7A
                             or 0xC1 <= enc[j] <= 0xF4):
                j += 1
            letters = CODE_ANY_RE.sub(
                lambda mm: (RU_CODE_INV.get(mm.group(0))
                            or EN_CODE_INV[mm.group(0)]).encode("ascii"),
                enc[i + 1:j])
            out += untranslit_word(letters.decode("ascii")).encode("utf-8")
            i = j
            if i < n and enc[i] == 0x00:   # терминатор после помеченного слова
                i += 1
            lit = i
            continue
        if 0x80 <= b <= 0x8F:
            out += enc[lit:i]
            out += list(WORD_TOKENS)[b - 0x80].encode("ascii")
            i += 1
            lit = i
            continue
        if 0xC1 <= b <= 0xD0:
            out += enc[lit:i]
            out += EN_CODE_INV[bytes([b])].encode("ascii")
            i += 1
            lit = i
            continue
        i += 1
    out += enc[lit:]
    return bytes(out)

# ═══════════════ Часть 3. V-byte ═══════════════
CYR_ORDER = "абвгдеёжзийклмнопрстуфхцчшщъыьэюя"
CODE_LO = {c: 0x80 + i for i, c in enumerate(CYR_ORDER)}            # 0x80..0xA0
CODE_UP = {c.upper(): 0xA1 + i for i, c in enumerate(CYR_ORDER)}    # 0xA1..0xC1
ALL_CODE = {**CODE_LO, **CODE_UP}
# В V-byte латиница остаётся ASCII без сжатия: триграммы только RU (по кириллице)
RU_TRI_B = {g: 0xC2 + i for i, g in enumerate(RU_TRI_CYR)}          # 0xC2..0xF5
BYTE_PAT = {g: bytes([CODE_LO[c] for c in g]) for g in RU_TRI_CYR}
TRI_B_RE = re.compile(b"|".join(re.escape(BYTE_PAT[g]) for g in
                                sorted(BYTE_PAT, key=lambda g: -len(g))))
TRI_B_MAP = {BYTE_PAT[g]: bytes([RU_TRI_B[g]]) for g in RU_TRI_CYR}
TRI_B_CYR = {bytes([RU_TRI_B[g]]): g for g in RU_TRI_CYR}


def encode_byte():
    parts = []
    for lit, run in zip(lits, runs):
        if lit:
            parts.append(wrap_all(lit.encode("utf-8")))
        if run[0].lower() in SPEC_THEIR:
            parts.append(bytes([ALL_CODE[c] for c in run]))
        else:
            parts.append(run.encode("ascii"))
    parts.append(wrap_all(lits[-1].encode("utf-8")))
    data = b"".join(parts)
    out, prev = [], 0
    for m in re.finditer(rb"[\x80-\xC1]+", data):
        out.append(data[prev:m.start()])
        out.append(TRI_B_RE.sub(lambda mm: TRI_B_MAP[mm.group(0)], m.group(0)))
        prev = m.end()
    out.append(data[prev:])
    return b"".join(out)


def decode_byte(enc):
    out = bytearray()
    i = 0
    n = len(enc)
    while i < n:
        b = enc[i]
        if b == 0xFF:
            ln = enc[i + 1]
            out += enc[i + 2:i + 2 + ln]
            i += 2 + ln
            continue
        if 0x80 <= b <= 0xA0:
            out += CYR_ORDER[b - 0x80].encode("utf-8")
            i += 1
            continue
        if 0xA1 <= b <= 0xC1:
            out += CYR_ORDER[b - 0xA1].upper().encode("utf-8")
            i += 1
            continue
        if b >= 0xC2 and bytes([b]) in TRI_B_CYR:
            out += TRI_B_CYR[bytes([b])].encode("utf-8")
            i += 1
            continue
        out.append(b)
        i += 1
    return bytes(out)

# ═══════════════ Запуск прототипов ═══════════════
print("\n=== 2-3. Прототипы на всём FB2 ===")
xz = lambda b: lzma.compress(b, format=lzma.FORMAT_XZ, preset=6)
z3 = zstd.ZstdCompressor(level=3)
res = {}
for name, enc_f, dec_f in (("marker", encode_marker, decode_marker),
                           ("byte", encode_byte, decode_byte)):
    t0 = time.perf_counter()
    enc = enc_f()
    enc_s = time.perf_counter() - t0
    dec = dec_f(enc)
    ok = dec == fb2_bytes
    diff_ctx = None
    if not ok:
        for i, (a, b2) in enumerate(zip(fb2_bytes, dec)):
            if a != b2:
                diff_ctx = {"pos": i,
                            "orig": fb2_bytes[max(0, i - 50):i + 50].decode("utf-8", "replace"),
                            "got": dec[max(0, i - 50):i + 50].decode("utf-8", "replace"),
                            "len_orig": len(fb2_bytes), "len_dec": len(dec)}
                print(f"  РАСХОЖДЕНИЕ @ {i}:")
                print(f"   orig: {diff_ctx['orig']!r}")
                print(f"   got : {diff_ctx['got']!r}")
                break
    t0 = time.perf_counter()
    dec_f(enc)
    dec_s = time.perf_counter() - t0
    sxz, sz3 = len(xz(enc)), len(z3.compress(enc))
    res[name] = {"bytes": len(enc), "xz6": sxz, "zstd3": sz3,
                 "enc_s": round(enc_s, 2), "dec_s": round(dec_s, 2),
                 "roundtrip": ok, "diff": diff_ctx}
    print(f"{name}: {len(enc):,} Б | xz {sxz:,} | zstd-3 {sz3:,} | "
          f"enc {enc_s:.1f}с dec {dec_s:.1f}с | roundtrip {'OK' if ok else 'FAIL'}")

# ═══════════════ Часть 4. varint базы-1000 ═══════════════
def pack_int(n, max_groups=8):
    groups = []
    while n:
        groups.append(n % 1000)
        n //= 1000
    if not groups or len(groups) > max_groups:
        return None
    out = bytearray([0xF0 + len(groups) - 1])
    acc = nbits = 0
    body = bytearray()
    for g in groups:                    # младшая группа первой, 10 бит на группу
        acc |= g << nbits
        nbits += 10
        while nbits >= 8:
            body.append(acc & 0xFF)
            acc >>= 8
            nbits -= 8
    if nbits:
        body.append(acc & 0xFF)
    return bytes(out) + bytes(body)


def unpack_int(data, pos):
    ng = (data[pos] & 0x07) + 1
    acc = nbits = 0
    i = pos + 1
    vals = []
    while len(vals) < ng:
        while nbits >= 10 and len(vals) < ng:
            vals.append(acc & 0x3FF)
            acc >>= 10
            nbits -= 10
        if len(vals) < ng:
            acc |= data[i] << nbits
            nbits += 8
            i += 1
    return sum(v * 1000 ** k for k, v in enumerate(vals)), i


rng = random.Random(20261120)
var_res = {}
for label, gen, cnt in (("12-значные", lambda: rng.randint(1, 10 ** 12 - 1), 300000),
                        ("24-значные", lambda: rng.randint(10 ** 23, 10 ** 24 - 1), 100000)):
    nums = [gen() for _ in range(cnt)]
    ascii_b = "\n".join(map(str, nums)).encode()
    packed = bytearray()
    pos, rt = 0, True
    for n in nums:
        p = pack_int(n)
        packed += p
        v, pos2 = unpack_int(bytes(p), 0)
        if v != n:
            rt = False
    packed = bytes(packed)
    digits = sum(len(str(n)) for n in nums)
    var_res[label] = {"ascii": len(ascii_b), "packed": len(packed),
                      "xz_ascii": len(xz(ascii_b)), "xz_packed": len(xz(packed)),
                      "digits": digits, "roundtrip": rt}
    print(f"varint {label}: ascii {len(ascii_b):,} -> {len(packed):,} Б; "
          f"xz {var_res[label]['xz_ascii']:,} -> {var_res[label]['xz_packed']:,}; "
          f"roundtrip {'OK' if rt else 'FAIL'}")

# ═══════════════ Часть 5. inline-равенства ═══════════════
INLINE_EQ = re.compile(r"(?<![\w.])(\d{1,9})([+\-*/×·/:÷])(\d{1,9})=(\d{1,15})(?![\w.])")
hits = INLINE_EQ.findall(text)


def _arith(a, op, b, c):
    a, b, c = int(a), int(b), int(c)
    return {"+": a + b == c, "-": a - b == c, "*": a * b == c, "×": a * b == c,
            "·": a * b == c, "/": bool(b) and a == b * c,
            ":": bool(b) and a == b * c, "÷": bool(b) and a == b * c}.get(op, False)


exact = [h for h in hits if _arith(*h)]
demo = ("Отчёт: план 20/5=4 смены, выручка 3*2=6 млн, итого 7+5=12 позиций. " * 40)
demo_after = INLINE_EQ.sub(
    lambda m: f"{m.group(1)}{m.group(2)}{m.group(3)}"
    if _arith(*m.groups()) else m.group(0), demo)
print(f"\n=== 5. inline-равенства в FB2: {len(hits)} (точных {len(exact)}) ===")
print(f"math-в-прозе демо: {len(demo.encode())} -> {len(demo_after.encode())} Б")

json.dump({"audit": {"fail_single": fail_single, "fail_pairs": fail_pairs,
                     "fail_triples": fail_triples[:20],
                     "n_fail_triples": len(fail_triples),
                     "latin_demo": latin_demo,
                     "fix_fail": fail_fix[:6]},
           "fb2": {"bytes": len(fb2_bytes), "chars": len(text),
                   "cyr_runs": n_cyr, "latin_runs": n_latin,
                   "adj_cyr_latin": adj_cyr_latin, "adj_latin_cyr": adj_latin_cyr},
           "variants": res, "varint": var_res,
           "inline_eqs": {"hits": len(hits), "exact": len(exact)},
           "math_prose_demo": {"before": len(demo.encode()),
                               "after": len(demo_after.encode())}},
          open(os.path.join(DIR, "results.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
print("saved: results.json")
