"""Тесты побайтового roundtrip для всех кодеков и контейнера.

Запуск из корня репозитория: python -m unittest discover -s tests -v

Сжатие проверяется через все три статистических компрессора контейнера:
xz (LZMA2), zstd и gzip — свойство побайтовой обратимости обязано выполняться
для каждого. Property-тест (T-08 из разбора skor-skeleton) гоняет 1000
случайных строк на собственном LCG без внешних зависимостей.
"""
import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from algebraic import container as C
from algebraic import crc16, numeq, numseries, textcodec, textlayer, varint
from algebraic.datasets import gen_equations, gen_journal, gen_random, gen_text

try:
    import zstandard  # noqa: F401
    HAS_ZSTD = True
except ImportError:
    HAS_ZSTD = False

BACKENDS = ("xz", "zstd", "gzip")

_DATASETS = [
    ("equations", gen_equations(80_000, seed=6)),
    ("journal", gen_journal(80_000, seed=7)),
    ("ru", gen_text("ru", 60_000)),
    ("en", gen_text("en", 60_000)),
    ("zh", gen_text("zh", 60_000)),
    ("ja", gen_text("ja", 60_000)),
    ("ar", gen_text("ar", 60_000)),
    ("emoji", gen_text("emoji", 60_000)),
    ("random", gen_random(50_000)),
    ("empty", b""),
    ("non-utf8", b"\xff\xfe\x00binary\xff"),
]


class TestNumEq(unittest.TestCase):
    def test_roundtrip_mixed_valid_invalid(self):
        data = (gen_equations(200_000, seed=1)
                + "это не равенство\n".encode("utf-8")
                + b"5*5=26\n"
                + b"007+1=8\n"
                + b"!\n"
                + gen_equations(100_000, seed=2))
        enc = numeq.compact_equations(data.decode("utf-8"))
        self.assertEqual(numeq.solve_missing_parts(enc).encode("utf-8"), data)

    def test_examples_from_concept(self):
        # Кодек всегда выбирает КРАТЧАЙШУЮ из корректных форм:
        for orig, comp in [
            ("27*761=20547", "27*761"),
            ("80136/756=106", "80136/756"),
            ("32099+29257=61356", "32099+29257"),
            ("8072-4166=3906", "8072-4166"),
            ("4839^2=23415921", "4839^2"),
            # Формы с пропущенным операндом выигрывают, когда результат короче:
            ("1000000-999999=1", "1000000-=1"),
            ("99999999/33333333=3", "99999999/=3"),
        ]:
            self.assertEqual(numeq.compact_line(orig), comp)
            self.assertEqual(numeq.solve_line(comp), orig)


class TestNumSeries(unittest.TestCase):
    def test_roundtrip_snapshots(self):
        for snap in (0, 7, 1000):
            data = gen_journal(300_000, seed=3) + "мусорная строка\n".encode("utf-8")
            enc = numseries.compact_journal(data.decode("utf-8"), snapshot_every=snap)
            self.assertEqual(
                numseries.rebuild_from_deltas(enc).encode("utf-8"), data,
                msg=f"snapshot_every={snap}",
            )

    def test_delta_smaller_than_full(self):
        data = gen_journal(2_000_000, seed=4)
        enc = numseries.compact_journal(data.decode("utf-8"))
        self.assertLess(len(enc.encode("utf-8")), len(data) // 10)


class TestTextCodec(unittest.TestCase):
    def test_roundtrip_all_scripts(self):
        cases = [
            "быстрая речь о числах и коде, снова речь и снова код",
            "the quick red fox again the quick red fox again",
            "森林里的鸟看光，城市的光走水路，森林里的鸟看光",
            "川が水を走る。でも山は光る。川が水を走る。",
            "كتاب جميل في مدينة، شمس كبيرة تشرق، كتاب جميل",
            "🙂🌍🔥hi 🌟🚀🔥run 🙂🌍🔥hi",
            "а", "", "!!!", "12" * 50,
            "aaa", "aaaa", "aaaaa", "a" * 100, "abab" * 30, "aba" * 40,
        ]
        for s in cases:
            pruned = textcodec.prune_text(s)
            self.assertIsInstance(pruned, bytes)
            self.assertEqual(textcodec.restore_text(pruned), s, msg=repr(s))

    def test_prune_smaller_on_repetitive(self):
        s = ("The quiet forest waits for the light. " * 200)
        self.assertLess(len(textcodec.prune_text(s)), len(s.encode("utf-8")))


class TestCrc16(unittest.TestCase):
    def test_check_value(self):
        # Контрольное значение CRC-16/CCITT-FALSE для «123456789» — 0x29B1.
        self.assertEqual(crc16.crc16_ccitt(b"123456789"), 0x29B1)

    def test_matches_reference_table_implementation(self):
        # Независимая побитовая реализация (как в спеке skor-skeleton).
        table = []
        for b in range(256):
            c = b << 8
            for _ in range(8):
                c = ((c << 1) ^ 0x1021) if c & 0x8000 else (c << 1)
                c &= 0xFFFF
            table.append(c)
        data = "проверка crc 12345".encode("utf-8") + bytes(range(256)) + b"\x00\xff"
        crc = 0xFFFF
        for byte in data:
            crc = ((crc << 8) & 0xFFFF) ^ table[((crc >> 8) ^ byte) & 0xFF]
        self.assertEqual(crc16.crc16_ccitt(data), crc)


class TestVarint(unittest.TestCase):
    def test_pack_header_and_roundtrip(self):
        cases = {1: 0xF0, 999: 0xF0, 1000: 0xF1, 999999: 0xF1,
                 1000000: 0xF2, 12345678901: 0xF3, 10 ** 12 - 1: 0xF3,
                 10 ** 24 - 1: 0xF7}
        for n, hdr in cases.items():
            p = varint.pack_int(n)
            self.assertEqual(p[0], hdr, msg=str(n))
            self.assertEqual(varint.unpack_int(p, 0), (n, len(p)), msg=str(n))
        self.assertIsNone(varint.pack_int(10 ** 25))  # > 24 цифр

    def test_truncated_raises(self):
        p = varint.pack_int(123456789012)
        with self.assertRaises(ValueError):
            varint.unpack_int(p[:-1], 0)

    def test_encode_decode_digits_roundtrip(self):
        text = ("план 12345 смен, итог 123456789012345678901234, дробь 3.14, "
                "слово abc12345def, ведущие нули 0012345, короткое 1234, "
                "журнал -1234567890123 и снова 98765432109876")
        enc = varint.encode_digits(text.encode("utf-8"))
        self.assertIsNotNone(enc)
        self.assertLess(len(enc), len(text.encode("utf-8")))
        self.assertEqual(varint.decode_digits(enc).decode("utf-8"), text)

    def test_encode_digits_skips(self):
        # эмодзи (байты 0xF0-0xF4) — слой неприменим;
        # короткие числа — замен нет;
        # ведущие нули — не каноничная запись, слой не включается.
        self.assertIsNone(varint.encode_digits("🙂🌍🔥".encode("utf-8")))
        self.assertIsNone(varint.encode_digits("короткие числа 1234".encode("utf-8")))
        self.assertIsNone(varint.encode_digits("нули 0012345".encode("utf-8")))


class TestTextLayer(unittest.TestCase):
    CASES = [
        "быстрая речь о числах и коде, снова речь и снова код",
        "ЩЁЛК, ПОДЪЁЗД, МЫШЬ И ЕЩЁ ОДНО СЛОВО",           # заглавные + ъ/ь/ы/э/щ
        "мывчоквжёсткийъэlc",                              # все «не-мнемонические» коды
        "the quick red fox again",                         # латиница как есть
        "Нa Скайлейн-авеню",                               # кириллица|латиница вплотную
        "тире — и неразрывный пробел:\xa0да",
        "строки\r\nс CRLF\r\nпереводами",
        "🙂🌍🔥 и эмодзи 🚀",
        "森林里的鸟看光",                                   # CJK — весь в RAW
        "\x7f-байт внутри",                                 # 0x7F литерально
        "а", "", "!!!", "1234567890",
    ]

    def test_roundtrip(self):
        for s in self.CASES:
            data = s.encode("utf-8")
            self.assertEqual(textlayer.decode_text_layer(
                textlayer.encode_text_layer(data)), data, msg=repr(s))

    def test_smaller_on_cyrillic(self):
        data = gen_text("ru", 60_000)
        enc = textlayer.encode_text_layer(data)
        self.assertLess(len(enc), len(data))

    def test_bad_codes_raise(self):
        for bad in (b"\xf6", b"\xfe", b"\xff", b"\xff\x05ab", b"\xff\x00"):
            with self.assertRaises(ValueError, msg=repr(bad)):
                textlayer.decode_text_layer(bad)


class TestContainer(unittest.TestCase):
    def test_roundtrip_every_kind(self):
        for name, data in _DATASETS:
            frame = C.compress_bytes(data)
            self.assertEqual(C.decompress_bytes(frame), data, msg=name)
            self.assertLessEqual(len(frame), len(data) + 32, msg=name)

    def test_roundtrip_every_kind_all_backends(self):
        """MAF2 с каждым из трёх компрессоров: xz (LZMA2), zstd, gzip."""
        for backend in BACKENDS:
            for name, data in _DATASETS:
                frame = C.compress_bytes(data, backend=backend)
                self.assertEqual(frame[:4], C.MAGIC2, msg=f"{backend}/{name}")
                self.assertEqual(C.decompress_bytes(frame), data,
                                 msg=f"{backend}/{name}")
                # несжимаемое хранится как есть: 15 (header) + 2 (CRC) байта
                self.assertLessEqual(len(frame), len(data) + 17,
                                     msg=f"{backend}/{name}")

    @unittest.skipUnless(HAS_ZSTD, "zstandard не установлен")
    def test_compressible_shrinks_with_every_backend(self):
        for backend in BACKENDS:
            data = gen_text("ru", 60_000)
            frame = C.compress_bytes(data, backend=backend)
            self.assertLess(len(frame), len(data), msg=backend)

    def test_journal_with_snapshots_in_container(self):
        data = gen_journal(100_000, seed=8)
        frame = C.compress_bytes(data, snapshot_every=1000)
        self.assertEqual(C.decompress_bytes(frame), data)

    def test_textlayer_candidate_used_on_cyrillic(self):
        data = gen_text("ru", 60_000)
        frame = C.compress_bytes(data)
        flags = frame[5]
        self.assertTrue(flags & C.FLAG_CODEC, "текстовый слой должен применяться")

    def test_maf1_frames_still_decoded(self):
        # Легаси-кадр MAF1 (флаг 1 = xz RAW) обязан читаться новым контейнером.
        data = gen_text("ru", 30_000)
        legacy = C.MAGIC + bytes((C.KIND_IDS["ALPHA_TEXT"], 1)) \
            + struct.pack(">Q", len(data)) + C._compress(data, "xz")
        self.assertEqual(C.decompress_bytes(legacy), data)

    def test_bad_frame(self):
        with self.assertRaises(ValueError):
            C.decompress_bytes(b"NOPE" + b"\x00" * 20)
        with self.assertRaises(ValueError):
            C.decompress_bytes(C.MAGIC + bytes((99, 0)) + b"\x00" * 8)
        with self.assertRaises(ValueError):
            C.decompress_bytes(C.MAGIC2 + bytes((99, 0, 0)) + b"\x00" * 8)

    def test_corruption_detected_with_every_backend(self):
        """Порча ЛЮБОГО байта кадра (CRC покрывает header+payload) -> ValueError."""
        data = gen_text("ru", 40_000)
        for backend in BACKENDS:
            frame = C.compress_bytes(data, backend=backend)
            positions = list(range(min(15, len(frame)))) + [len(frame) - 1, len(frame) - 2]
            stride = max(1, len(frame) // 400)
            positions += list(range(15, len(frame) - 2, stride))
            for pos in positions:
                bad = frame[:pos] + bytes((frame[pos] ^ 0xFF,)) + frame[pos + 1:]
                with self.assertRaises(ValueError, msg=f"{backend}@{pos}"):
                    C.decompress_bytes(bad)


class TestPropertyRoundtrip(unittest.TestCase):
    """T-08: 1000 случайных строк из алфавита [a-z, а-я, 0-9, пробел, ']
    на собственном LCG (константные семена, без внешних зависимостей)."""

    _POOL = ("abcdefghijklmnopqrstuvwxyz"
             "абвгдеёжзийклмнопрстуфхцчшщъыьэюя"
             "0123456789 '")
    _SEED = 20261120

    @staticmethod
    def _lcg(seed: int):
        state = seed
        while True:
            state = (6364136223846793005 * state
                     + 1442695040888963407) % (1 << 64)
            yield state >> 16

    def test_1000_random_strings_all_backends(self):
        gen = self._lcg(self._SEED)
        pool = self._POOL
        for backend in BACKENDS:
            gen = self._lcg(self._SEED)  # одинаковые строки для всех backend
            for i in range(1000):
                length = next(gen) % 61
                s = "".join(pool[next(gen) % len(pool)] for _ in range(length))
                data = s.encode("utf-8")
                frame = C.compress_bytes(data, backend=backend)
                self.assertEqual(C.decompress_bytes(frame), data,
                                 msg=f"{backend} #{i}: {s!r}")


if __name__ == "__main__":
    unittest.main()
