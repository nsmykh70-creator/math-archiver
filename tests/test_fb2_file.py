"""Файловый цикл на срезе реального файла 677647.fb2 (2 МБ).

Полный файл (47 МБ) гоняется отдельно: python benchmarks/fb2_file_roundtrip.py.
Здесь — быстрый вариант: срез файла, кадр на диск, чтение с диска,
распаковка, сверка SHA-256, порча байта. Пропускается, если FB2 не найден.
"""
import hashlib
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from algebraic import container as C

FB2 = os.environ.get("MATH_ARCHIVER_FB2", "/home/z/my-project/upload/677647.fb2")
SLICE = 2_000_000


@unittest.skipUnless(os.path.exists(FB2), f"{FB2} не найден")
class TestFb2FileCycle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(FB2, "rb") as f:
            cls.data = f.read(SLICE)
        # срез обязан заканчиваться на границе UTF-8 символа
        while cls.data[-1] & 0xC0 == 0x80:
            cls.data = cls.data[:-1]

    def test_compress_decompress_file_cycle_all_backends(self):
        with tempfile.TemporaryDirectory() as tmp:
            src_sha = hashlib.sha256(self.data).hexdigest()
            for backend in ("xz", "zstd", "gzip"):
                frame = C.compress_bytes(self.data, backend=backend)
                path = os.path.join(tmp, f"slice.maf2.{backend}")
                with open(path, "wb") as f:
                    f.write(frame)
                with open(path, "rb") as f:
                    from_disk = f.read()
                restored = C.decompress_bytes(from_disk)
                self.assertEqual(restored, self.data, msg=backend)
                rest_path = path + ".restored"
                with open(rest_path, "wb") as f:
                    f.write(restored)
                with open(rest_path, "rb") as f:
                    self.assertEqual(hashlib.sha256(f.read()).hexdigest(), src_sha,
                                     msg=f"SHA-256 не совпал ({backend})")
                os.remove(rest_path)
                # порча байта в середине нагрузки -> CRC-16 обязан поймать
                mid = len(from_disk) // 2
                bad = from_disk[:mid] + bytes((from_disk[mid] ^ 0xFF,)) \
                    + from_disk[mid + 1:]
                with self.assertRaises(ValueError, msg=f"{backend}: порча не поймана"):
                    C.decompress_bytes(bad)


if __name__ == "__main__":
    unittest.main()
