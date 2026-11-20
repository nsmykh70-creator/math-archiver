"""Текстовый кодек без потерь: литералы + битовая карта предсказаний.

Адаптивный двухуровневый предсказатель (пара символов -> символ, затем
одиночный символ -> символ): совпавший с предсказанием символ не записывается
в литеральный поток. Позиции всех пропусков передаются ЯВНО — битовой картой
(1 бит на символ исходника, 1 = литерал, 0 = предсказан), поэтому декодер
всегда знает, где он в потоке, и рассинхронизация невозможна.

Статистика строится ТОЛЬКО по литералам, поэтому кодер и декодер всегда
в одинаковом состоянии. Формат: "<число символов исходника>\\n" + биты
(ceil(n/8) байт, старший бит первым) + UTF-8 литералы.

Работает с любыми письменностями: кириллица, латиница, CJK (иероглифы и
кана), арабская вязь, эмодзи — всё, что является корректным Unicode-текстом.
На случайном тексте доля предсказаний мала, битовая карта раздувает поток —
и контейнер честно откатывается на исходные байты / xz.
"""
from collections import defaultdict


def _argmax(d):
    if not d:
        return None
    return max(d.items(), key=lambda kv: (kv[1], kv[0]))[0]


def prune_text(text: str) -> bytes:
    """Исходный текст -> заголовок с длиной + биты + UTF-8 литералы."""
    l1 = {}
    l2 = {}
    total = len(text)
    bits = bytearray((total + 7) // 8)
    literals = []
    prev1 = None
    prev2 = None
    for idx, ch in enumerate(text):
        pred = None
        if prev2 is not None:
            d = l2.get(prev2)
            if d:
                pred = _argmax(d)
        if pred is None:
            d1 = l1.get(prev1)
            if d1:
                pred = _argmax(d1)
        if pred is not None and pred == ch:
            prev2 = prev1 + ch
            prev1 = ch
            continue
        literals.append(ch)
        bits[idx >> 3] |= 0x80 >> (idx & 7)
        d1 = l1.get(prev1)
        if d1 is None:
            d1 = l1[prev1] = defaultdict(int)
        d1[ch] += 1
        if prev2 is not None:
            key = prev2
            d2 = l2.get(key)
            if d2 is None:
                d2 = l2[key] = defaultdict(int)
            d2[ch] += 1
        prev2 = prev1 + ch if prev1 is not None else None
        prev1 = ch
    return (f"{total}\n".encode("utf-8") + bytes(bits)
            + "".join(literals).encode("utf-8"))


def restore_text(pruned: bytes) -> str:
    """Биты + литералы -> исходный текст."""
    try:
        head, body = pruned.split(b"\n", 1)
        total = int(head.decode("ascii"))
    except (ValueError, UnicodeDecodeError):
        raise ValueError("повреждённый поток текстового кодека") from None
    nb = (total + 7) // 8
    if len(body) < nb:
        raise ValueError("повреждённый поток текстового кодека")
    bits = body[:nb]
    try:
        literals = body[nb:].decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("повреждённый поток текстового кодека") from None
    l1 = {}
    l2 = {}
    out = []
    li = 0
    prev1 = None
    prev2 = None
    for idx in range(total):
        literal = bits[idx >> 3] & (0x80 >> (idx & 7))
        if literal:
            if li >= len(literals):
                raise ValueError("повреждённый поток текстового кодека")
            ch = literals[li]
            li += 1
            out.append(ch)
            d1 = l1.get(prev1)
            if d1 is None:
                d1 = l1[prev1] = defaultdict(int)
            d1[ch] += 1
            if prev2 is not None:
                key = prev2
                d2 = l2.get(key)
                if d2 is None:
                    d2 = l2[key] = defaultdict(int)
                d2[ch] += 1
            prev2 = prev1 + ch if prev1 is not None else None
            prev1 = ch
        else:
            pred = None
            if prev2 is not None:
                d = l2.get(prev2)
                if d:
                    pred = _argmax(d)
            if pred is None:
                d1 = l1.get(prev1)
                if d1:
                    pred = _argmax(d1)
            if pred is None:
                raise ValueError("повреждённый поток текстового кодека")
            out.append(pred)  # статистика не меняется — кодер так же
            prev2 = prev1 + pred
            prev1 = pred
    if li != len(literals):
        raise ValueError("повреждённый поток текстового кодека")
    return "".join(out)
