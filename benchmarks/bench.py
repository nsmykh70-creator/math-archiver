"""Бенчмарк: наборы данных, кандидаты сжатия, таблицы результатов.

Запуск из корня репозитория: python benchmarks/bench.py [--quick]
Пишет benchmarks/RESULTS.md и обновляет таблицу в README.md между
маркерами <!-- BENCH:START --> / <!-- BENCH:END -->.

Методика повторяет эксперимент: исходник (100%), LZMA2 (xz) в одиночку,
формула (слой 2) в одиночку, формула + LZMA2 (связка), контейнер MAF1
(авто-выбор). Все варианты проверяются побайтовым roundtrip.
"""
import argparse
import os
import sys
import time

import lzma

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from algebraic import container as C
from algebraic.datasets import gen_equations, gen_journal, gen_random, gen_text

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIB = 1024 * 1024
XZ_FILTERS = [{"id": lzma.FILTER_LZMA2, "preset": 6}]


def xz(b: bytes) -> bytes:
    return lzma.compress(b, format=lzma.FORMAT_RAW, filters=XZ_FILTERS)


def nfmt(n: int) -> str:
    """12 345 678 — пробел-разделитель тысяч."""
    return f"{n:,}".replace(",", " ")


def size_cell(n: int) -> str:
    if n >= MIB // 2:
        return f"{n / MIB:.2f} МБ".replace(".", ",")
    return f"{n / 1024:.1f} КБ".replace(".", ",")


def gain_cell(orig: int, comp: int) -> str:
    if comp == orig:
        return "—"
    if comp >= orig:
        return f"+{(comp - orig) / orig * 100:.2f}% (расширение)".replace(".", ",")
    times = orig / comp
    return f"−{100 - comp / orig * 100:.2f}% (в ~{times:.1f} раза)".replace(".", ",")


def row(name: str, orig: int, comp: int) -> str:
    return (f"| {name} | {size_cell(comp)} | {nfmt(comp)} Б | {nfmt(comp * 8)} бит "
            f"| {comp / orig * 100:.2f}% | {gain_cell(orig, comp)} |".replace(".", ","))


def bench_dataset(name: str, data: bytes, snapshot: int = 0,
                  snapshot_label: str = "") -> str:
    kind = C.detect_kind(data)
    print(f"=== {name}: {len(data)} байт, тип {kind} ===", flush=True)

    if kind == "BIN":
        enc = data
        t_enc = t_dec = 0.0
        xz_enc = None
    else:
        t0 = time.perf_counter()
        enc = C._codec_encode(kind, data, 0)  # чистая формула, без снапшотов
        t_enc = time.perf_counter() - t0
        t0 = time.perf_counter()
        dec = C._codec_decode(kind, enc)
        t_dec = time.perf_counter() - t0
        assert dec == data, f"кодек {kind}: roundtrip провален"
        xz_enc = xz(enc)

    t0 = time.perf_counter()
    xz_raw = xz(data)
    t_xz = time.perf_counter() - t0

    t0 = time.perf_counter()
    frame = C.compress_bytes(data, snapshot_every=snapshot)
    t_c = time.perf_counter() - t0
    assert C.decompress_bytes(frame) == data, "контейнер: roundtrip провален"
    best = len(frame) - C.HEADER_LEN

    rows = [
        row("Исходные данные", len(data), len(data)),
        row("Исходник + LZMA2 (xz)", len(data), len(xz_raw)),
    ]
    if kind != "BIN":
        rows += [
            row("Только формула (слой 2)", len(data), len(enc)),
            row("Формула + LZMA2 (слой 2+3)", len(data), len(xz_enc)),
        ]
    if snapshot:
        enc2 = C._codec_encode(kind, data, snapshot)
        xz_enc2 = xz(enc2)
        rows.append(row(f"Формула + снапшоты {snapshot_label}", len(data), len(enc2)))
        rows.append(row(f"Формула + снапшоты + LZMA2", len(data), len(xz_enc2)))
    rows.append(row("Контейнер MAF1 (итог, авто-выбор)", len(data), best))

    head = (f"| Вариант записи | Объём | Байты | Биты | Доля от исходника | Выигрыш |\n"
            f"|---|---|---|---|---|---|\n")
    def secs(t: float) -> str:
        return f"{t:.2f}".replace(".", ",")

    times = (f"\n*Время: формула {secs(t_enc)} с (декод {secs(t_dec)} с), "
             f"xz {secs(t_xz)} с, контейнер {secs(t_c)} с.*")
    return head + "\n".join(rows) + times


def update_readme(tables_md: str) -> None:
    start = "<!-- BENCH:START -->"
    end = "<!-- BENCH:END -->"
    p = os.path.join(ROOT, "README.md")
    with open(p, encoding="utf-8") as f:
        txt = f.read()
    i = txt.index(start) + len(start)
    j = txt.index(end)
    with open(p, "w", encoding="utf-8") as f:
        f.write(txt[:i] + "\n\n" + tables_md + "\n" + txt[j:])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="уменьшить объёмы в 10 раз")
    args = ap.parse_args()
    k = MIB // 10 if args.quick else MIB

    sections = []
    tables_md = []

    data_eq = gen_equations(10 * k, seed=7)
    sections.append(("## 1. Независимые равенства (умножение, деление, +, -, квадраты, кубы) — 10 МБ",
                     bench_dataset("равенства", data_eq)))

    data_jr = gen_journal(10 * k, seed=11)
    sections.append(("## 2. Журнал состояний (цепочка x op k = b, числа растут снежным комом) — 10 МБ",
                     bench_dataset("журнал", data_jr, snapshot=1000, snapshot_label="(каждые 1000 шагов)")))

    for lang, title in (("ru", "Кириллица"), ("en", "Латиница"),
                        ("zh", "Иероглифы"), ("ja", "Японский"),
                        ("ar", "Арабская вязь"), ("emoji", "Эмодзи")):
        data_t = gen_text(lang, 2 * k)
        sections.append((f"## {3 + list(('ru','en','zh','ja','ar','emoji')).index(lang)}. "
                         f"Текст ({title}) — 2 МБ",
                         bench_dataset(f"текст {lang}", data_t)))

    data_rnd = gen_random(4 * k)
    sections.append(("## 9. Случайные байты (предел Шеннона) — 4 МБ",
                     bench_dataset("случайные байты", data_rnd)))

    out = ["# Результаты бенчмарка math-archiver",
           "",
           "Методика: для каждого набора сравниваются — исходник (100%), LZMA2 (xz, preset 6) "
           "в одиночку, формула (слой 2) в одиночку, связка «формула + LZMA2» и итоговый "
           "контейнер MAF1 (авто-выбор лучшего проверенного варианта). Каждый вариант "
           "проверяется побайтовым roundtrip: восстановленные данные обязаны совпасть "
           "с исходными. Биты = байты × 8, МБ = 1 048 576 байт (MiB).",
           ""]
    for title, body in sections:
        out += [title, "", body, ""]
    out_path = os.path.join(ROOT, "benchmarks", "RESULTS.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    print(f"\nотчёт: {out_path}")

    tables_md.append("### Сводная таблица (лучший проверенный вариант контейнера)\n\n"
                     "| Набор данных | Исходник | Итог MAF1 | Доля | Выигрыш |\n|---|---|---|---|---|\n")
    for title, body in sections:
        rows = [ln for ln in body.split("\n") if ln.startswith("| Контейнер MAF1")]
        if not rows:
            continue
        cells = [c.strip() for c in rows[0].strip("|").split("|")]
        name = title.split(". ", 1)[1].split(" — ")[0]
        tables_md.append(f"| {name} | {cells[1]} | {cells[2]} | {cells[4]} | {cells[5]} |\n")
    update_readme("".join(tables_md))
    print("README.md обновлён между маркерами BENCH.")


if __name__ == "__main__":
    main()
