"""Varint базы-1000: длинные целые литералы -> 10 бит на группу из 3 цифр.

Идея заимствована из спецификации skor-skeleton v1 (Layer 1, правило 1.1).
Заголовок 0xF0 + (число групп - 1), максимум 8 групп (до 24 знаков); группы —
10-битные значения базы-1000, упакованные бит-писателем с аккумулятором,
младшая группа первой (спека не фиксирует порядок групп — здесь порядок
выбран и задокументирован). 5 цифр -> 3 байта вместо 5, 24 цифры -> 11 байт
вместо 24; на случайных длинных числах это даёт ~5% экономии даже поверх xz.

Слой применяется к UTF-8 тексту без астральных символов: байты 0xF0-0xF4 —
лидирующие байты четырёхбайтовых UTF-8 последовательностей (эмодзи и т.п.) —
конфликтуют с заголовками varint, поэтому при их наличии кодер честно
отказывается от слоя (в спецификации skor-skeleton этот конфликт не учтён).
"""
import re

MAX_GROUPS = 8  # до 24 цифр

_DIGITS_RE = re.compile(r"(?<!\w)([0-9]{5,24})(?!\w)")
_ASTRAL_RE = re.compile(rb"[\xf0-\xf4]")


def pack_int(n: int):
    """Целое -> байты varint; None, если больше 24 цифр."""
    groups = []
    while n:
        groups.append(n % 1000)
        n //= 1000
    if not groups or len(groups) > MAX_GROUPS:
        return None
    out = bytearray((0xF0 + len(groups) - 1,))
    acc = nbits = 0
    body = bytearray()
    for g in groups:  # младшая группа первая
        acc |= g << nbits
        nbits += 10
        while nbits >= 8:
            body.append(acc & 0xFF)
            acc >>= 8
            nbits -= 8
    if nbits:
        body.append(acc & 0xFF)
    return bytes(out) + bytes(body)


def unpack_int(data: bytes, pos: int):
    """Байты varint с позиции pos -> (значение, новая позиция)."""
    ng = (data[pos] & 0x07) + 1
    acc = nbits = 0
    i = pos + 1
    vals = []
    while len(vals) < ng:
        while nbits >= 10 and len(vals) < ng:
            vals.append(acc & 0x3FF)
            acc >>= 10
            nbits -= 10
        if len(vals) < ng:
            if i >= len(data):
                raise ValueError("обрезанный varint")
            acc |= data[i] << nbits
            nbits += 8
            i += 1
    return sum(v * 1000 ** k for k, v in enumerate(vals)), i


def encode_digits(data: bytes):
    """Заменить в UTF-8 тексте целые литералы (5-24 цифр, на границах \\w,
    без ведущих нулей) на varint-байты. None — слой неприменим."""
    if not data or _ASTRAL_RE.search(data):
        return None
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    out = []
    prev = 0
    changed = False
    for m in _DIGITS_RE.finditer(text):
        s = m.group(1)
        if s[0] == "0":
            continue
        packed = pack_int(int(s))
        if packed is None:
            continue
        changed = True
        out.append(text[prev:m.start()].encode("utf-8"))
        out.append(packed)
        prev = m.end()
    if not changed:
        return None
    out.append(text[prev:].encode("utf-8"))
    return b"".join(out)


def decode_digits(data: bytes) -> bytes:
    """Обратное преобразование: байтовый автомат, 0xF0-0xF7 -> varint."""
    out = bytearray()
    i = 0
    n = len(data)
    while i < n:
        b = data[i]
        if 0xF0 <= b <= 0xF7:
            val, i = unpack_int(data, i)
            out += str(val).encode("ascii")
        else:
            out.append(b)
            i += 1
    return bytes(out)
