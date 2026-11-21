"""CLI: compress / decompress / info."""
import argparse
import hashlib

from .container import compress_bytes, decompress_bytes, detect_kind


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="algebraic",
        description="Алгебраическое сжатие: данные = формула (затравка + операции).",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    cp = sub.add_parser("compress", help="сжать файл (контейнер MAF2)")
    cp.add_argument("infile")
    cp.add_argument("outfile")
    cp.add_argument("--snapshot", type=int, default=0,
                    help="снапшот каждые N шагов журнала (0 — выключено)")
    cp.add_argument("--backend", choices=("xz", "zstd", "gzip"), default="xz",
                    help="статистический компрессор (по умолчанию xz/LZMA2)")

    dp = sub.add_parser("decompress", help="распаковать контейнер MAF1/MAF2")
    dp.add_argument("infile")
    dp.add_argument("outfile")

    ip = sub.add_parser("info", help="тип данных и размеры")
    ip.add_argument("infile")

    args = p.parse_args(argv)

    with open(args.infile, "rb") as f:
        data = f.read()

    if args.cmd == "info":
        kind = detect_kind(data)
        print(f"файл: {args.infile}; байт: {len(data)}; тип: {kind}")
        return 0

    if args.cmd == "compress":
        out = compress_bytes(data, snapshot_every=args.snapshot, backend=args.backend)
        with open(args.outfile, "wb") as f:
            f.write(out)
        if data:
            print(f"{len(data)} -> {len(out)} байт (экономия {100 - len(out) / len(data) * 100:.2f}%)")
            print(f"sha256 исходника: {hashlib.sha256(data).hexdigest()}")
        else:
            print("пустой файл")
        return 0

    out = decompress_bytes(data)
    with open(args.outfile, "wb") as f:
        f.write(out)
    print(f"восстановлено {len(out)} байт")
    print(f"sha256: {hashlib.sha256(out).hexdigest()} — сравните с исходником")
    return 0
