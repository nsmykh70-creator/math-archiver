"""Генераторы детерминированных тестовых данных (фиксированный seed)."""
import random


def gen_equations(target: int, seed: int = 7) -> bytes:
    """Независимые верные равенства a op b = c: +, -, *, /, ^2, ^3."""
    rng = random.Random(seed)
    lines = []
    size = 0
    while size < target:
        op = rng.choices("+-*/^", weights=[30, 22, 14, 24, 10])[0]
        if op == "^":
            a = rng.randint(2, 99999)
            e = rng.choice((2, 3))
            ln = f"{a}^{e}={a ** e}"
        elif op == "*":
            a = rng.randint(1, 99999)
            b = rng.randint(1, 99999)
            ln = f"{a}*{b}={a * b}"
        elif op == "/":
            b = rng.randint(1, 9999)
            c = rng.randint(1, 99999)
            ln = f"{b * c}/{b}={c}"
        elif op == "+":
            a = rng.randint(1, 99999)
            b = rng.randint(1, 99999)
            ln = f"{a}+{b}={a + b}"
        else:
            a = rng.randint(1, 99999)
            b = rng.randint(1, a)
            ln = f"{a}-{b}={a - b}"
        lines.append(ln)
        size += len(ln) + 1
    return ("\n".join(lines) + "\n").encode("utf-8")


def gen_journal(target: int, seed: int = 11) -> bytes:
    """Полный журнал состояний: первая строка — затравка, далее a op k = b,
    где a — итог предыдущей строки. Числа растут «снежным комом» после *k
    (как в эксперименте: длина чисел не ограничена)."""
    rng = random.Random(seed)
    x = rng.randint(100, 9999)
    lines = [str(x)]
    size = len(str(x)) + 1
    while size < target:
        op = rng.choices("+-*", weights=[55, 15, 30])[0]
        if op == "-" and x > 1:
            k = rng.randint(1, min(x - 1, 999))
            y = x - k
        elif op == "*":
            k = rng.randint(2, 9)
            y = x * k
        else:
            op = "+"
            k = rng.randint(1, 999)
            y = x + k
        ln = f"{x}{op}{k}={y}"
        lines.append(ln)
        size += len(ln) + 1
        x = y
    return ("\n".join(lines) + "\n").encode("utf-8")


_VOCAB = {
    "ru": dict(
        adj=["быстрый", "красный", "большой", "тихий", "зимний", "новый", "старый",
             "светлый", "тёмный", "высокий", "ранний", "спокойный"],
        noun=["поток", "лес", "город", "дом", "ветер", "экран", "мост", "сад",
              "поезд", "камень", "солнечный", "луч"],
        verb=["бежит", "стоит", "растёт", "спит", "светит", "ждёт", "звенит",
              "молчит", "идёт", "горит", "шумит", "падает"],
        obj=["дорогу", "речь", "солнце", "воду", "код", "план", "файл", "мир",
             "число", "текст", "лес", "свет"],
        adv=["быстро", "медленно", "рядом", "снова", "вечно", "вслух", "внизу",
             "вместе", "утром", "днём"],
    ),
    "en": dict(
        adj=["quick", "red", "large", "quiet", "cold", "new", "old", "bright",
             "dark", "tall", "calm", "early"],
        noun=["stream", "forest", "city", "house", "wind", "screen", "bridge",
              "garden", "train", "stone", "light", "sun"],
        verb=["runs", "stands", "grows", "sleeps", "shines", "waits", "rings",
              "stays", "walks", "burns", "hums", "falls"],
        obj=["road", "speech", "sun", "water", "code", "plan", "file", "world",
             "number", "text", "forest", "light"],
        adv=["fast", "slowly", "nearby", "again", "always", "aloud", "below",
             "together", "today", "early"],
    ),
    "zh": dict(
        noun=["森林", "城市", "风", "光", "水", "山", "路", "鸟", "书", "朋友", "太阳", "河"],
        verb=["走", "看", "听", "写", "来", "说", "吃", "读", "跑", "想", "等", "亮"],
        obj=["水", "路", "书", "信", "茶", "饭", "字", "画", "歌", "梦", "山", "光"],
    ),
    "ja": dict(
        noun=["川", "山", "本", "光", "水", "町", "道", "鳥", "花", "友達", "太陽", "森"],
        verb=["走る", "見る", "聞く", "書く", "来る", "話す", "食べる", "読む",
              "歩く", "考える", "待つ", "光る"],
        obj=["水", "道", "本", "手紙", "お茶", "ご飯", "字", "絵", "歌", "夢", "山", "光"],
    ),
    "ar": dict(
        noun=["كتاب", "مدينة", "نهر", "شمس", "ماء", "جبل", "طريق", "طائر",
              "زهرة", "صديق", "نور", "غابة"],
        verb=["يجري", "يقف", "ينمو", "ينام", "يشرق", "ينتظر", "يقرأ", "يكتب",
              "يمشي", "يضيء", "يسمع", "يرى"],
        adj=["كبير", "صغير", "جميل", "سريع", "قوي", "جديد", "قديم", "هادئ"],
    ),
    "emoji": dict(
        a=["🙂", "🌍", "🔥", "🚀", "🌟", "🐱", "🍕", "⚽", "🎵", "💡"],
        b=["🌤️", "📚", "🍀", "🎉", "❤️", "🌈", "☕", "🎯", "🧭", "🧩"],
        w=["go", "run", "hi", "ok", "wow", "top"],
    ),
}


def _sentence(lang: str, rng: random.Random) -> str:
    v = _VOCAB[lang]
    pick = rng.choice
    if lang == "ru":
        return f"{pick(v['adj'])} {pick(v['noun'])} {pick(v['verb'])} {pick(v['obj'])} {pick(v['adv'])}."
    if lang == "en":
        return f"The {pick(v['adj'])} {pick(v['noun'])} {pick(v['verb'])} {pick(v['obj'])} {pick(v['adv'])}."
    if lang == "zh":
        return f"{pick(v['noun'])}{pick(v['verb'])}{pick(v['obj'])}，{pick(v['noun'])}{pick(v['verb'])}。"
    if lang == "ja":
        return f"{pick(v['noun'])}が{pick(v['obj'])}を{pick(v['verb'])}。でも{pick(v['noun'])}は{pick(v['verb'])}。"
    if lang == "ar":
        return f"{pick(v['adj'])} {pick(v['noun'])} {pick(v['verb'])} في {pick(v['noun'])}."
    return f"{pick(v['a'])}{pick(v['b'])}{pick(v['b'])}{pick(v['w'])} {pick(v['a'])}{pick(v['a'])}{pick(v['b'])}!"


def gen_text(lang: str, target: int, seed: int = 5) -> bytes:
    """Многоязычный «природоподобный» текст: шаблоны предложений со
    случайными подстановками — высокая локальная предсказуемость."""
    rng = random.Random(seed + len(lang))
    lines = []
    size = 0
    while size < target:
        s = _sentence(lang, rng)
        lines.append(s)
        size += len(s.encode("utf-8")) + 1
    return ("\n".join(lines) + "\n").encode("utf-8")


def gen_random(n: int, seed: int = 42) -> bytes:
    """Случайные байты (предел Шеннона: сжаться не должно)."""
    return random.Random(seed).randbytes(n)
