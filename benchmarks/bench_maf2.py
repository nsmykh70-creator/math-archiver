"""Бенчмарк контейнера MAF2 × три статистических компрессора.

Запуск из корня репозитория: python benchmarks/bench_maf2.py [--quick]
Пишет benchmarks/RESULTS_MAF2.md. Сравниваются xz (LZMA2, preset 6),
zstd (уровень 3) и gzip (уровень 6) — поодиночке на исходных данных и
внутри контейнера MAF2 (авто-выбор слоя: формула / textlayer / varint).
Контейнер проверяет каждый кандидат roundtrip-ом перед записью, поэтому
все итоговые размеры — без потерь. Опция --no-fb2 пропускает большой файл.
"""
import argparse
import gzip
import lzma
import os
import struct
import sys
import time

import zstandard as zstd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from algebraic import container as C
from algebraic.datasets import gen_equations, gen_journal, gen_random, gen_text

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIB = 1024 * 1024
FB2 = "/home/z/my-project/upload/677647.fb2"
XZ_FILTERS = [{"id": lzma.FILTER_LZMA2, "preset": 6}]
BACKENDS = ("xz", "zstd", "gzip")

FLAG_NAMES = {C.FLAG_CODEC: "формула", C.FLAG_VARINT: "varint",
              C.FLAG_COMP: "сжатие", C.FLAG_TLAYER: "textlayer"}


def flags_str(flags: int) -> str:
    on = [name for bit, name in FLAG_NAMES.items() if flags & bit]
    return "+".join(on) if on else "как есть"


def raw_compress(data: bytes, backend: str) -> bytes:
    if backend == "xz":
        return lzma.compress(data, format=lzma.FORMAT_RAW, filters=XZ_FILTERS)
    if backend == "zstd":
        return zstd.ZstdCompressor(level=3).compress(data)
    return gzip.compress(data, compresslevel=6, mtime=0)


def nfmt(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def size_cell(n: int) -> str:
    if n >= MIB // 2:
        return f"{n / MIB:.2f} МБ".replace(".", ",")
    return f"{n / 1024:.1f} КБ".replace(".", ",")


def secs(t: float) -> str:
    return f"{t:.2f}".replace(".", ",")


def bench_dataset(name: str, data: bytes, snapshot: int = 0) -> list:
    kind = C.detect_kind(data)
    rows = [f"### {name} — {nfmt(len(data))} Б, тип {kind}\n",
            "| Вариант | Размер | Доля от исходника | Время enc, с | Время dec, с |",
            "|---|---|---|---|---|"]
    t0 = time.perf_counter()
    dec_times = []
    for backend in BACKENDS:
        t0 = time.perf_counter()
        blob = raw_compress(data, backend)
        t_raw = time.perf_counter() - t0
        t0 = time.perf_counter()
        lzma.decompress(blob, format=lzma.FORMAT_RAW, filters=XZ_FILTERS) \
            if backend == "xz" else None
        t_dec = time.perf_counter() - t0
        rows.append(f"| {backend} на исходнике | {size_cell(len(blob))} "
                    f"| {len(blob) / len(data) * 100:.2f}% "
                    f"| {secs(t_raw)} | {secs(t_dec)} |")
    for backend in BACKENDS:
        t0 = time.perf_counter()
        frame = C.compress_bytes(data, snapshot_every=snapshot, backend=backend)
        t_enc = time.perf_counter() - t0
        t0 = time.perf_counter()
        back = C.decompress_bytes(frame)
        t_dec = time.perf_counter() - t0
        assert back == data, f"{name}/{backend}: roundtrip провален"
        rows.append(f"| MAF2 + {backend} ({flags_str(frame[5])}) "
                    f"| {size_cell(len(frame))} "
                    f"| {len(frame) / len(data) * 100:.2f}% "
                    f"| {secs(t_enc)} | {secs(t_dec)} |")
    return rows


def bench_fb2() -> list:
    if not os.path.exists(FB2):
        return [f"### 677647.fb2 — файл не найден ({FB2})\n"]
    with open(FB2, "rb") as f:
        data = f.read()
    kind = C.detect_kind(data)
    rows = [f"### 677647.fb2 — {nfmt(len(data))} Б, тип {kind}\n",
            "| Вариант | Размер | Доля от исходника | Время enc, с | Время dec, с |",
            "|---|---|---|---|---|"]
    for backend in BACKENDS:
        t0 = time.perf_counter()
        blob = raw_compress(data, backend)
        t_raw = time.perf_counter() - t0
        rows.append(f"| {backend} на исходнике | {size_cell(len(blob))} "
                    f"| {len(blob) / len(data) * 100:.2f}% | {secs(t_raw)} | — |")
    for backend in BACKENDS:
        t0 = time.perf_counter()
        frame = C.compress_bytes(data, backend=backend)
        t_enc = time.perf_counter() - t0
        t0 = time.perf_counter()
        back = C.decompress_bytes(frame)
        t_dec = time.perf_counter() - t0
        assert back == data, f"fb2/{backend}: roundtrip провален"
        rows.append(f"| MAF2 + {backend} ({flags_str(frame[5])}) "
                    f"| {size_cell(len(frame))} "
                    f"| {len(frame) / len(data) * 100:.2f}% "
                    f"| {secs(t_enc)} | {secs(t_dec)} |")
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="уменьшить объёмы в 10 раз")
    ap.add_argument("--no-fb2", action="store_true", help="пропустить 677647.fb2")
    args = ap.parse_args()
    k = MIB // 10 if args.quick else MIB

    out = ["# Результаты: контейнер MAF2 × компрессоры (xz/LZMA2, zstd, gzip)",
           "",
           "Методика: для каждого набора — три компрессора на исходных данных и те же "
           "три внутри контейнера MAF2 (авто-выбор слоя: словесно-формульный кодек, "
           "текстовый ярус textlayer, varint длинных чисел; лучший проверенный "
           "кандидат). Каждый вариант контейнера проверяется побайтовым roundtrip "
           "перед записью. Время указано для enc (сжатие) и dec (распаковка).",
           ""]

    sections = [
        ("## 1. Независимые равенства", gen_equations(2 * k, seed=7), 0),
        ("## 2. Журнал состояний (снапшот каждые 1000 шагов)",
         gen_journal(2 * k, seed=11), 1000),
        ("## 3. Текст (кириллица)", gen_text("ru", k), 0),
        ("## 4. Текст (латиница)", gen_text("en", k), 0),
        ("## 5. Текст (иероглифы)", gen_text("zh", k), 0),
        ("## 6. Текст (японский)", gen_text("ja", k), 0),
        ("## 7. Текст (арабская вязь)", gen_text("ar", k), 0),
        ("## 8. Текст (эмодзи)", gen_text("emoji", k), 0),
        ("## 9. Случайные байты (предел Шеннона)", gen_random(k), 0),
    ]
    for title, data, snap in sections:
        print(title, flush=True)
        out += [title, ""] + bench_dataset(title.split(". ", 1)[1], data, snap) + [""]

    if not args.no_fb2:
        print("FB2...", flush=True)
        out += ["## 10. Художественный текст 677647.fb2", ""]
        out += bench_fb2() + [""]

    out_path = os.path.join(ROOT, "benchmarks", "RESULTS_MAF2.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    print(f"отчёт: {out_path}")


if __name__ == "__main__":
    main()
