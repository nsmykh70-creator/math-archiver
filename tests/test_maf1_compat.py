"""Совместимость со старым форматом MAF1 (контейнер образца 5eeb8f8).

Старые кадры (без CRC, flags: 0 — как есть, 1 — xz, 2 — textcodec,
3 — textcodec+xz) обязаны читаться текущим кодом без потерь: textcodec.py
не менялся с самого первого коммита, ветка совместимости маршрутизирует
их в тот же кодек. Без этого теста ветка могла бы молча протухнуть.
"""
import lzma
import struct
import unittest

from algebraic import container as C

TEXT = ("""<?xml version="1.0" encoding="UTF-8"?>
<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0">
<body><title>Глава первая. Прибытковские лестницы</title>
<p>— Вы яхненники свили себе гнездо прямо в оранжерее, — сказала
Оля, не оборачиваясь. — Придётся ждать до сентября.</p>
<p>Он не ответил: цифры 1924, 1985 и 2001 складывались сами.</p>
</body></FictionBook>
""").encode("utf-8") * 30


def _build_maf1(kind: str, flag: int, data: bytes) -> bytes:
    """Кадр ровно в формате старого контейнера (заголовок 14 байт, без CRC)."""
    blob = data
    if flag & 2:
        blob = C._codec_encode(kind, blob)
    if flag & 1:
        blob = lzma.compress(blob, format=lzma.FORMAT_RAW,
                             filters=C._XZ_FILTERS)
    return C.MAGIC + bytes((C.KIND_IDS[kind], flag)) \
        + struct.pack(">Q", len(data)) + blob


class TestMaf1Compat(unittest.TestCase):
    def test_all_flag_variants_roundtrip(self):
        kind = C.detect_kind(TEXT)
        self.assertEqual(kind, "ALPHA_TEXT")
        for flag in (0, 1, 2, 3):
            with self.subTest(flag=flag):
                frame = _build_maf1(kind, flag, TEXT)
                self.assertEqual(C.decompress_bytes(frame), TEXT)

    def test_corrupted_maf1_raises(self):
        # у MAF1 нет CRC, но контракт модуля: любая порча — ValueError
        frame = _build_maf1("ALPHA_TEXT", 3, TEXT)
        bad = frame[:-50] + bytes(b ^ 0xFF for b in frame[-50:])
        with self.assertRaises(ValueError):
            C.decompress_bytes(bad)


if __name__ == "__main__":
    unittest.main()
