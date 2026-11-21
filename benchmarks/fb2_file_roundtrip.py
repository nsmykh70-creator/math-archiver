"""Сквозной тест на реальном файле 677647.fb2: сжатие -> диск -> чтение ->
восстановление -> побайтовая сверка.

Запуск из корня репозитория: python benchmarks/fb2_file_roundtrip.py

Для каждого бэкенда (xz/LZMA2, zstd, gzip) контейнер MAF2:
  1. сжимает файл в памяти (с внутренним roundtrip-ом кандидата),
  2. пишет кадр .maf2 на диск,
  3. перечитывает его с диска и распаковывает,
  4. сверяет восстановленное с исходником и по байтам, и по SHA-256,
  5. портит один байт кадра и требует ValueError от CRC-16.

Дополнительно для бэкенда xz прогоняется CLI-путь целиком на полном файле:
python -m algebraic compress / decompress, сверка cmp + SHA-256.
Артефакты .maf2 пишутся в download/fb2_test/; восстановленные файлы
проверяются и удаляются (они побайтово равны исходнику).
"""
import hashlib
import os
import shutil
import subprocess
import sys
import time

import zstandard as zstd  # noqa: F401  (нужен контейнеру для backend="zstd")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from algebraic import container as C

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FB2 = os.environ.get("MATH_ARCHIVER_FB2", "/home/z/my-project/upload/677647.fb2")
OUT = os.path.join(ROOT, "..", "fb2_test")

BACKENDS = ("xz", "zstd", "gzip")


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def nfmt(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def secs(t: float) -> str:
    return f"{t:.2f}".replace(".", ",")


def main() -> int:
    if not os.path.exists(FB2):
        print(f"файл не найден: {FB2}")
        return 1
    os.makedirs(OUT, exist_ok=True)
    with open(FB2, "rb") as f:
        data = f.read()
    kind = C.detect_kind(data)
    orig_sha = hashlib.sha256(data).hexdigest()
    print(f"файл: {FB2}\nразмер: {nfmt(len(data))} Б, тип {kind}\n"
          f"sha256 исходника: {orig_sha}\n", flush=True)

    rows = ["| Бэкенд | Кадр .maf2, Б | Доля | enc, с | dec, с | SHA-256 совпал | Порча -> ValueError |",
            "|---|---|---|---|---|---|---|"]
    for backend in BACKENDS:
        # 1. сжатие (внутри контейнера кандидат уже проверен roundtrip-ом)
        t0 = time.perf_counter()
        frame = C.compress_bytes(data, backend=backend)
        t_enc = time.perf_counter() - t0
        flags = frame[5]
        name = f"677647.fb2.maf2.{backend}"
        path = os.path.join(OUT, name)

        # 2. кадр на диск
        with open(path, "wb") as f:
            f.write(frame)

        # 3. чтение с диска и распаковка
        with open(path, "rb") as f:
            from_disk = f.read()
        t0 = time.perf_counter()
        restored = C.decompress_bytes(from_disk)
        t_dec = time.perf_counter() - t0

        # 4. сверка: байты в памяти + SHA-256 восстановленного файла на диске
        restored_path = path + ".restored"
        with open(restored_path, "wb") as f:
            f.write(restored)
        ok_bytes = restored == data and from_disk == frame
        ok_sha = sha256_file(restored_path) == orig_sha
        os.remove(restored_path)

        # 5. порча одного байта в середине нагрузки -> CRC обязан поймать
        mid = len(frame) // 2
        bad = from_disk[:mid] + bytes((from_disk[mid] ^ 0xFF,)) + from_disk[mid + 1:]
        try:
            C.decompress_bytes(bad)
            corruption = "НЕТ — ОШИБКА"
        except ValueError:
            corruption = "да"

        flag_names = []
        if flags & C.FLAG_CODEC:
            flag_names.append("textlayer" if flags & C.FLAG_TLAYER else "формула")
        if flags & C.FLAG_VARINT:
            flag_names.append("varint")
        if flags & C.FLAG_COMP:
            flag_names.append(backend)
        stage = "+".join(flag_names) or "как есть"

        rows.append(f"| {backend} ({stage}) | {nfmt(len(frame))} "
                    f"| {len(frame) / len(data) * 100:.2f}% | {secs(t_enc)} "
                    f"| {secs(t_dec)} | {'да' if ok_bytes and ok_sha else 'НЕТ'} "
                    f"| {corruption} |")
        print(f"[{backend}] {nfmt(len(data))} -> {nfmt(len(frame))} Б "
              f"({len(frame) / len(data) * 100:.2f}%), enc {secs(t_enc)} с, "
              f"dec {secs(t_dec)} с, sha_ok={ok_bytes and ok_sha}, "
              f"corruption_caught={corruption == 'да'}", flush=True)

    # CLI-путь целиком на полном файле (бэкенд xz — лучший по сжатию)
    cli_row = ""
    cli_maf2 = os.path.join(OUT, "677647.fb2.cli.maf2")
    cli_restored = cli_maf2 + ".restored"
    t0 = time.perf_counter()
    subprocess.run([sys.executable, "-m", "algebraic", "compress", FB2, cli_maf2,
                    "--backend", "xz"], cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
    t_cli_enc = time.perf_counter() - t0
    t0 = time.perf_counter()
    subprocess.run([sys.executable, "-m", "algebraic", "decompress", cli_maf2,
                    cli_restored], cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
    t_cli_dec = time.perf_counter() - t0
    cli_same = (sha256_file(FB2) == sha256_file(cli_restored)
                and open(cli_maf2, "rb").read()[:4] == C.MAGIC2)
    os.remove(cli_restored)
    cli_size = os.path.getsize(cli_maf2)
    cli_row = (f"\n\nCLI на полном файле (`algebraic compress/decompress --backend xz`): "
               f"{nfmt(cli_size)} Б ({cli_size / len(data) * 100:.2f}%), "
               f"enc {secs(t_cli_enc)} с, dec {secs(t_cli_dec)} с, "
               f"SHA-256 исходника и восстановления совпали: "
               f"{'да' if cli_same else 'НЕТ'}.")
    print(f"[cli xz] {nfmt(cli_size)} Б, sha_ok={cli_same}", flush=True)

    report = ["# Сквозной тест файла 677647.fb2 (MAF2): сжатие и восстановление",
              "",
              f"Исходник: `{FB2}` — {nfmt(len(data))} Б, тип {kind}.",
              f"SHA-256 исходника: `{orig_sha}`.",
              "",
              "Для каждого бэкенда: сжатие контейнером MAF2, запись кадра на диск,",
              "чтение с диска, распаковка, сверка по байтам и по SHA-256, порча",
              "одного байта кадра в середине нагрузки (CRC-16 обязан поймать).",
              "Восстановленные файлы побайтово равны исходнику и удалены после сверки;",
              "кадры .maf2 сохранены в download/fb2_test/.",
              "",
              "\n".join(rows), cli_row, ""]
    rep_path = os.path.join(ROOT, "benchmarks", "FB2_ROUNDTRIP_REPORT.md")
    with open(rep_path, "w", encoding="utf-8") as f:
        f.write("\n".join(report))
    print(f"\nотчёт: {rep_path}", flush=True)
    return 0 if all(r.split("|")[6].strip() == "да" for r in rows[2:]) and cli_same else 1


if __name__ == "__main__":
    sys.exit(main())
