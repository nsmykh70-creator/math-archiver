#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Бенчмарк обратимого 1-байтового кодека кириллицы на 677647.fb2.

Режимы:
  closed — маркеры ~слово~ с двух сторон (как в скрипте пользователя),
           плюс экранирование литеральной тильды (фикс коллизии);
  open   — закрывающий маркер только если за словом идёт символ из
           CHARS_66 (иначе конец слова виден и без него): экономит ~1 Б/слово.
Сверка с числами пользователя: closed на этом файле байт-в-байт совпадает
с его запуском (тильд в файле 0, экранирование не меняет выход).
Дополнительно: gzip-6, xz-6, zstd-3, zstd-19, микро-пакет со словарём zstd,
кодек проекта textcodec.prune_text как база сравнения. Все результаты
пишутся в results.json после каждой стадии.
Запуск: python3 bench_reversible.py (из этой папки; FB2 берётся из upload/).
"""
import gzip
import json
import lzma
import os
import re
import sys
import time

import zstandard

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, REPO)
from algebraic import textcodec  # noqa: E402

FB2 = "/home/z/my-project/upload/677647.fb2"
HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = {}

# ── таблица пользователя (дословно, для воспроизводимости размеров) ──
CHARS_66 = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_!#$"
LOWER_CYR = "абвгдеёжзийклмнопрстуфхцчшщъыьэюя"
ALL_CYR = LOWER_CYR + LOWER_CYR.upper()
assert len(CHARS_66) == len(set(CHARS_66)) == 66 and len(ALL_CYR) == 66
TO_1BYTE = {c: b for c, b in zip(ALL_CYR, CHARS_66)}
FROM_1BYTE = {b: c for c, b in TO_1BYTE.items()}
CHARS_SET = set(CHARS_66)
ESC = "\x7f"  # экранирование литеральной '~'; в FB2 её 0, как и \x7f

CYR_WORD_RE = re.compile(r"[А-Яа-яЁё]+")
XML_PROTECT_RE = re.compile(r"(<binary\b[^>]*>.*?</binary>|<[^>]+>)", flags=re.DOTALL)


def encode_text(text: str, mode: str = "closed") -> str:
    """Кириллические слова -> ~код~ (closed) или ~код (open). '~' экранируется."""
    assert ESC not in text, "в исходнике есть \\x7f — экранирование сломается"
    text = text.replace("~", ESC)

    def enc_part(part: str) -> str:
        out, last = [], 0
        for m in CYR_WORD_RE.finditer(part):
            s, e = m.span()
            out.append(part[last:s])
            out.append("~")
            out.append("".join(TO_1BYTE[c] for c in m.group(0)))
            nxt = part[e] if e < len(part) else ""
            # закрывающий маркер обязателен, если дальше идёт символ
            # алфавита (иначе он прилипнет к слову) или часть кончилась
            if mode == "closed" or nxt in CHARS_SET or e == len(part):
                out.append("~")
            last = e
        out.append(part[last:])
        return "".join(out)

    parts = XML_PROTECT_RE.split(text)
    return "".join(p if (not p or p.startswith("<")) else enc_part(p) for p in parts)


def decode_text(enc: str) -> str:
    """Линейный парсер: '~'+[CHARS_66]+(+ '~')? -> слово; ESC -> '~'."""
    out, i, n = [], 0, len(enc)
    while i < n:
        c = enc[i]
        if c == ESC:
            out.append("~")
            i += 1
        elif c == "~":
            j = i + 1
            while j < n and enc[j] in CHARS_SET:
                j += 1
            if j == i + 1:
                raise ValueError(f"одиночная '~' без слова в позиции {i}")
            out.append("".join(FROM_1BYTE[ch] for ch in enc[i + 1:j]))
            i = j + 1 if (j < n and enc[j] == "~") else j  # съесть закрывающий
        else:
            out.append(c)
            i += 1
    return "".join(out)


# ── архиваторы ──
def gz(b):
    return gzip.compress(b, compresslevel=6, mtime=0)


def xz(b):
    return lzma.compress(b, format=lzma.FORMAT_XZ, preset=6)


_ZC = {3: zstandard.ZstdCompressor(level=3), 19: zstandard.ZstdCompressor(level=19)}


def zstd(b, lvl):
    return _ZC[lvl].compress(b)


def save():
    with open(os.path.join(HERE, "results.json"), "w", encoding="utf-8") as f:
        json.dump(RESULTS, f, ensure_ascii=False, indent=1)


def stage(name):
    print(f"[{time.strftime('%H:%M:%S')}] {name}", flush=True)


# ══════════════════ 0. коллизия на синтетике ══════════════════
stage("0. коллизия с литеральной '~'")
tricky = "abc~def~ 5слово да~нет ~ещё~ детектив"
# логика пользователя без экранирования:
user_enc = re.sub(r"[А-Яа-яЁё]+",
                  lambda m: "~" + "".join(TO_1BYTE[c] for c in m.group(0)) + "~", tricky)
user_dec = re.sub(r"~([%s]+)~" % re.escape(CHARS_66),
                  lambda m: "".join(FROM_1BYTE[c] for c in m.group(1)), user_enc)
RESULTS["collision"] = {"sample": tricky, "user_roundtrip_ok": user_dec == tricky}
print(f"  кодек пользователя на 'abc~def~...': roundtrip {'OK' if user_dec == tricky else 'СЛОМАН: ' + user_dec!r}")
for mode in ("closed", "open"):
    enc = encode_text(tricky, mode)
    dec = decode_text(enc)
    ok = dec == tricky
    RESULTS["collision"][f"fixed_{mode}_ok"] = ok
    RESULTS["collision"][f"fixed_{mode}_encoded"] = enc
    print(f"  fixed[{mode}]: roundtrip {'OK' if ok else 'FAIL'} | {enc!r}")
save()

# ══════════════════ 1. файл ══════════════════
stage("1. чтение FB2")
orig_bytes = open(FB2, "rb").read()
text = orig_bytes.decode("utf-8", errors="strict")
RESULTS["file"] = {"bytes": len(orig_bytes), "chars": len(text)}
print(f"  {len(orig_bytes):,} Б, {len(text):,} символов")
save()

variants = {}
for mode in ("closed", "open"):
    stage(f"2. encode [{mode}]")
    t0 = time.perf_counter()
    enc_text = encode_text(text, mode)
    dt = time.perf_counter() - t0
    enc_bytes = enc_text.encode("utf-8")
    stage(f"2. decode [{mode}] + проверка")
    t1 = time.perf_counter()
    ok = decode_text(enc_text) == text
    dt_dec = time.perf_counter() - t1
    assert ok, f"roundtrip {mode} сломался!"
    variants[mode] = enc_bytes
    RESULTS[f"encode_{mode}"] = {"bytes": len(enc_bytes), "enc_s": round(dt, 2),
                                 "dec_s": round(dt_dec, 2), "roundtrip": True}
    print(f"  {len(enc_bytes):,} Б (orig {len(orig_bytes):,}), enc {dt:.1f} с, dec {dt_dec:.1f} с — roundtrip OK")
    del enc_text
    save()

# ══════════════════ 3. проектный кодек (предсказание символов) ══════════════════
stage("3. textcodec.prune_text (проект)")
t0 = time.perf_counter()
pruned = textcodec.prune_text(text)
dt = time.perf_counter() - t0
assert textcodec.restore_text(pruned) == text, "roundtrip prune сломался!"
variants["prune"] = pruned
RESULTS["encode_prune"] = {"bytes": len(pruned), "enc_s": round(dt, 2), "roundtrip": True}
print(f"  {len(pruned):,} Б за {dt:.1f} с — roundtrip OK")
save()

# ══════════════════ 4. сжатие всех вариантов ══════════════════
compressors = {"gzip6": gz, "xz6": xz, "zstd3": lambda b: zstd(b, 3),
               "zstd19": lambda b: zstd(b, 19)}
RESULTS["compress"] = {}
for vname, payload in [("orig", orig_bytes), ("closed", variants["closed"]),
                       ("open", variants["open"]), ("prune", variants["prune"])]:
    RESULTS["compress"][vname] = {}
    for cname, fn in compressors.items():
        stage(f"4. {cname} на {vname} ({len(payload):,} Б)")
        t0 = time.perf_counter()
        blob = fn(payload)
        dt = time.perf_counter() - t0
        RESULTS["compress"][vname][cname] = {"bytes": len(blob), "s": round(dt, 1)}
        print(f"  {len(blob):,} Б за {dt:.1f} с")
        save()

# ══════════════════ 5. микро-пакет: фраза + словарь zstd ══════════════════
stage("5. микро-пакет: фраза, словарь zstd по FB2")
phrases = {
    "RU": "Современный алгоритм сжимает большие данные за доли секунды.",
    "TR": "Svremeny algritm czimaet blshie dannye za doli skundy.",
    "EN": "Mdrn algrthm cmprsss lrge data in frctns of a scnd.",
}
sample_lines = [ln.strip().encode("utf-8") for ln in text.split("\n") if 40 < len(ln) < 400]
del text, variants["closed"], variants["open"], variants["prune"], orig_bytes
dic = zstandard.train_dictionary(65536, sample_lines[:20000])
zd = zstandard.ZstdCompressor(level=3, dict_data=dic)
RESULTS["micro"] = {}
for k, s in phrases.items():
    b = s.encode("utf-8")
    row = {"raw": len(b), "gzip6": len(gz(b)), "xz6": len(xz(b)),
           "zstd3": len(zstd(b, 3)), "zstd3_dict": len(zd.compress(b))}
    RESULTS["micro"][k] = row
    print(f"  {k}: raw {row['raw']} | gzip {row['gzip6']} | xz {row['xz6']} | "
          f"zstd {row['zstd3']} | zstd+dict {row['zstd3_dict']}")
RESULTS["micro_dict_bytes"] = len(dic.as_bytes())
print(f"  словарь: {len(dic.as_bytes())} Б (на приёмной стороне, не в пакете)")
save()
stage("Готово — results.json сохранён")
