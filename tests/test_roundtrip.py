"""Тесты побайтового roundtrip для всех кодеков и контейнера.

Запуск из корня репозитория: python -m unittest discover -s tests -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from algebraic import container as C
from algebraic import numeq, numseries, textcodec
from algebraic.datasets import gen_equations, gen_journal, gen_random, gen_text


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


class TestContainer(unittest.TestCase):
    def test_roundtrip_every_kind(self):
        datasets = [
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
        for name, data in datasets:
            frame = C.compress_bytes(data)
            self.assertEqual(C.decompress_bytes(frame), data, msg=name)
            self.assertLessEqual(len(frame), len(data) + 32, msg=name)

    def test_journal_with_snapshots_in_container(self):
        data = gen_journal(100_000, seed=8)
        frame = C.compress_bytes(data, snapshot_every=1000)
        self.assertEqual(C.decompress_bytes(frame), data)

    def test_bad_frame(self):
        with self.assertRaises(ValueError):
            C.decompress_bytes(b"NOPE" + b"\x00" * 20)
        with self.assertRaises(ValueError):
            C.decompress_bytes(C.MAGIC + bytes((99, 0)) + b"\x00" * 8)


if __name__ == "__main__":
    unittest.main()
