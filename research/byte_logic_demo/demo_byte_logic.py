#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Демо байтовой логики пользователя на реальном конвейере math-archiver.

1. Точные байты UTF-8/UTF-16 для примеров пользователя.
2. Равенства через numeq.compact_line (неявный результат/операнд) + roundtrip.
3. Слова через транслит + скелет + словарь двусмысленностей (lossless).
4. Сводный конвейер: слова + равенства -> предсжатие -> xz, все три уровня.
Запуск: python3 demo_byte_logic.py  (из research/byte_logic_demo/ репозитория)
"""
import json
import lzma
import os
import random
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO)

from algebraic import numeq, textcodec  # noqa: E402

# ────────────────────────── 1. Байты UTF-8 / UTF-16 ──────────────────────────
SAMPLES = ["локоть", "лкть", "лktь", "компьютер", "кмптр", "математика",
           "2*5=10", "2=10", "20/5=4", "20=5"]
rows = []
for s in SAMPLES:
    rows.append({"строка": s, "символов": len(s),
                 "utf8": len(s.encode("utf-8")),
                 "utf16le": len(s.encode("utf-16-le"))})
print("=== 1. Байтовые расчёты (проверка кодом) ===")
for r in rows:
    print(f"  {r['строка']:<12} символов={r['символов']:>2}  "
          f"UTF-8={r['utf8']:>2} Б  UTF-16LE={r['utf16le']:>2} Б")

# ────────────────────────── 2. Равенства: неявные формы ──────────────────────────
EQS = ["2*5=10", "20/5=4", "48*396=19008", "20/4=5", "968*876=847968",
       "810936/90104=9", "1077-560=517", "12+=27"]
print("\n=== 2. Равенства через numeq (предсжатие без потерь) ===")
eq_rows = []
for line in EQS:
    compact = numeq.compact_line(line)
    restored = numeq.solve_line(compact)
    ok = restored == line
    b_raw = len(line.encode("utf-8"))
    b_c = len(compact.encode("utf-8"))
    eq_rows.append({"исходник": line, "компакт": compact, "utf8_исх": b_raw,
                    "utf8_компакт": b_c, "roundtrip": ok})
    print(f"  {line:<18} -> {compact:<12} {b_raw} Б -> {b_c} Б   roundtrip={'OK' if ok else 'FAIL'}")

# ──────────────── 3. Слова: транслит + скелет + словарь ────────────────
CYR = {}
for a, b in zip("АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ",
                ["A", "B", "V", "G", "D", "E", "Yo", "Zh", "Z", "I", "Y", "K",
                 "L", "M", "N", "O", "P", "R", "S", "T", "U", "F", "Kh", "Ts",
                 "Ch", "Sh", "Shch", "", "Y", "", "E", "Yu", "Ya"]):
    CYR[a] = b
for a, b in zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
                ["a", "b", "v", "g", "d", "e", "yo", "zh", "z", "i", "y", "k",
                 "l", "m", "n", "o", "p", "r", "s", "t", "u", "f", "kh", "ts",
                 "ch", "sh", "shch", "", "y", "", "e", "yu", "ya"]):
    CYR[a] = b
VOWELS = set("aeiouyAEIOUY")


def translit(text):
    return "".join(CYR.get(c, c) for c in text)


def prune_word(w, keep_prefix=1):
    ch = list(w)
    if len(ch) <= 4 or not any(c.isalpha() for c in ch):
        return w
    out = ch[:keep_prefix]
    prev_cons = None
    for c in ch[keep_prefix:-1]:
        if c.isalpha():
            if c.lower() in VOWELS:
                continue
            low = c.lower()
            if prev_cons == low:
                continue
            prev_cons = low
            out.append(c)
        else:
            out.append(c)
    out.append(ch[-1])
    return "".join(out)


print("\n=== 3. Слова: транслит и скелет (одиночные примеры) ===")
word_rows = []
for w in ["локоть", "компьютер", "математика", "сжатие", "алгоритм"]:
    tr = translit(w)
    sk = prune_word(tr, 1)
    word_rows.append({"слово": w, "utf8": len(w.encode("utf-8")),
                      "транслит": tr, "байт_транслит": len(tr.encode("utf-8")),
                      "скелет": sk, "байт_скелет": len(sk.encode("utf-8"))})
    print(f"  {w:<11} {len(w.encode('utf-8')):>2} Б -> транслит {tr:<9} "
          f"{len(tr.encode('utf-8')):>2} Б -> скелет {sk:<7} {len(sk.encode('utf-8')):>2} Б")

# ──────────────── 4. Полный конвейер на смешанном корпусе ────────────────
def build_word_corpus():
    files = [os.path.join(REPO, "README.md"),
             os.path.join(REPO, "uhc", "README_RU.md")]
    lines, seen = [], set()
    for fp in files:
        with open(fp, encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if len(ln) < 40 or ln in seen:
                    continue
                cyr = sum(1 for c in ln if "а" <= c.lower() <= "я")
                if cyr * 2 >= len(ln):
                    seen.add(ln)
                    lines.append(ln)
    return "\n".join(lines)


def build_eq_corpus(n=2000, seed=20261120):
    rng = random.Random(seed)
    out = []
    while len(out) < n:
        a = rng.randint(2, 9999)
        b = rng.randint(2, 9999)
        op = rng.choice("+-*/")
        if op == "+":
            c = a + b
        elif op == "-":
            if b >= a:
                continue
            c = a - b
        elif op == "*":
            if a * b > 10 ** 12:
                continue
            c = a * b
        else:
            if a % b:
                continue
            c = a // b
        line = f"{a}{op}{b}={c}"
        if numeq.compact_line(line) != "!" + line:
            out.append(line)
    return out


def skeleton_lossless(tr_text):
    """Транслит -> скелет (режим 2) + словарь двусмысленностей (lossless)."""
    sk_words = [prune_word(w, 1) for w in tr_text.split(" ")]
    orig = tr_text.split(" ")
    pairs, amb = {}, {}
    for s, o in zip(sk_words, orig):
        if s == o:
            continue
        if s in pairs and pairs[s] != o:
            amb.setdefault(s, {pairs[s]}).add(o)
        else:
            pairs.setdefault(s, o)
    var = {s: sorted(v) for s, v in amb.items()}
    vidx = {s: {w: i for i, w in enumerate(sorted(v))} for s, v in amb.items()}
    positions = [[i, vidx[s][orig[i]]] for i, s in enumerate(sk_words) if s in var]
    amb_blob = json.dumps({"m": var, "p": positions}, ensure_ascii=False).encode("utf-8")
    # проверка обратной сборки
    amap = dict(positions)
    rebuilt = [var[s][amap[i]] if s in var else pairs.get(s, s)
               for i, s in enumerate(sk_words)]
    assert " ".join(rebuilt) == tr_text, "обратная сборка скелета сломалась"
    return " ".join(sk_words), amb_blob


def xz(b):
    return lzma.compress(b, format=lzma.FORMAT_XZ, preset=6 | lzma.PRESET_EXTREME)


print("\n=== 4. Сводный конвейер (слова + равенства), lossless на каждом уровне ===")
words = build_word_corpus()
eqs = build_eq_corpus()
words_b = words.encode("utf-8")
eqs_b = ("\n".join(eqs)).encode("utf-8")
raw = words_b + eqs_b

lvl0 = xz(words_b) + xz(eqs_b)  # просто xz
eq_compact = ("\n".join(numeq.compact_equations("\n".join(eqs)))).encode("utf-8")
assert all(numeq.solve_line(numeq.compact_line(l)) == l for l in eqs), \
    "roundtrip равенств сломался"
tr_words = translit(words)
sk, amb = skeleton_lossless(tr_words)
lvl1 = xz(words_b) + xz(eq_compact)  # предсжатие равенств
lvl2 = xz(sk.encode("utf-8")) + xz(amb) + xz(eq_compact)  # + скелет слов

p = lambda n: round(100.0 * n / len(raw), 2)
res = {"bytes_raw": len(raw), "bytes_words": len(words_b), "bytes_eq": len(eqs_b),
       "eq_lines": len(eqs),
       "lvl0_xz": len(lvl0), "lvl0_pct": p(len(lvl0)),
       "lvl1_eq_compact_xz": len(lvl1), "lvl1_pct": p(len(lvl1)),
       "lvl2_skeleton_xz": len(lvl2), "lvl2_pct": p(len(lvl2)),
       "amb_bytes": len(amb),
       "eq_compact_bytes": len(eq_compact), "eq_raw_bytes": len(eqs_b),
       "skeleton_bytes": len(sk.encode("utf-8")),
       "rows_bytes": rows, "rows_eq": eq_rows, "rows_words": word_rows,
       "numeq_examples_ok": all(r["roundtrip"] for r in eq_rows)}
print(f"  корпус: слова {len(words_b)} Б + равенства {len(eqs_b)} Б ({len(eqs)} строк) = {len(raw)} Б")
print(f"  L0  исходник + xz:                       {len(lvl0):>7} Б  {p(len(lvl0)):>6}%")
print(f"  L1  + неявные формы равенств (numeq):    {len(lvl1):>7} Б  {p(len(lvl1)):>6}%")
print(f"  L2  + транслит-скелет со словарём ({len(amb)} Б): {len(lvl2):>6} Б  {p(len(lvl2)):>6}%")

json.dump(res, open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "byte_logic_results.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
print("\nsaved: byte_logic_results.json")
