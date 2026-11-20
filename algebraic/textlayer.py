"""Текстовый ярус textlayer (схема V-byte) для кириллического текста.

Идея заимствована из спецификации skor-skeleton v1 (слои 1.5-3) и переработана:
вместо небиективного ASCII-транслита (аудит показал 75 битых пар и 3805 битых
троек) — однобайтовые коды кириллицы: 0x80-0xA0 строчные буквы, 0xA1-0xC1
заглавные (регистр сохранён), частотные триграммы — один байт 0xC2-0xF5.
Вся ASCII-пунктуация и латиница остаются литеральными байтами — коды и ASCII
не пересекаются, поэтому смежность «кириллица|латиница» («Нa» с латинской «a»)
безопасна по построению. Прочий не-ASCII (тире, NBSP, CJK, эмодзи) заворачивается
в RAW-блоки 0xFF + len + байты — их continuation-байты 0x80-0xBF не конфликтуют
с кодами, так как декодер копирует RAW-содержимое дословно.
"""
import re

CYR = "абвгдеёжзийклмнопрстуфхцчшщъыьэюя"
_LO = {c: 0x80 + i for i, c in enumerate(CYR)}            # 0x80..0xA0
_UP = {c.upper(): 0xA1 + i for i, c in enumerate(CYR)}    # 0xA1..0xC1
_ALL = {**_LO, **_UP}

_TRI = ["ено", "ное", "сто", "ого", "его", "ние", "ает", "ете", "ест",
        "тво", "при", "ето", "как", "ный", "ова", "ени", "ост", "ите",
        "тог", "ани", "нов", "ств", "енн", "ует", "нно", "еже", "гда",
        "оно", "обо", "тот", "дел", "вет", "гор", "пра", "час", "тся"]
_TRI_PAT = {g: bytes(_ALL[c] for c in g) for g in _TRI}    # паттерн в кодах
_TRI_CODE = {g: 0xC2 + i for i, g in enumerate(_TRI)}      # 0xC2..0xF5
_TRI_INV = {bytes([c]): g for g, c in _TRI_CODE.items()}
_PAT_CODE = {pat: bytes([_TRI_CODE[g]]) for g, pat in _TRI_PAT.items()}

_TRI_RE = re.compile(b"|".join(re.escape(p) for p in
                               sorted(_TRI_PAT.values(), key=len, reverse=True)))
_RAW_RE = re.compile(rb"[^\x00-\x7f]+")
_WORD_RE = re.compile(r"[А-Яа-яЁё]+|[A-Za-z]+")


def _wrap_raw(data: bytes) -> bytes:
    """Не-ASCII байты -> RAW-блоки 0xFF + len(1..255) + байты."""
    out = []
    prev = 0
    for m in _RAW_RE.finditer(data):
        out.append(data[prev:m.start()])
        frag = m.group(0)
        for i in range(0, len(frag), 255):
            chunk = frag[i:i + 255]
            out.append(b"\xff" + bytes([len(chunk)]) + chunk)
        prev = m.end()
    out.append(data[prev:])
    return b"".join(out)


def encode_text_layer(data: bytes) -> bytes:
    """UTF-8 текст -> поток кодов: кириллица 1 байт/букву, триграммы 1 байт,
    латиница и ASCII как есть, прочий не-ASCII в RAW-блоках."""
    text = data.decode("utf-8")
    parts = []
    prev = 0
    for m in _WORD_RE.finditer(text):
        lit = text[prev:m.start()]
        run = m.group(0)
        prev = m.end()
        if lit:
            parts.append(_wrap_raw(lit.encode("utf-8")))
        if run[0] in _ALL:
            codes = bytes(_ALL[c] for c in run)
            parts.append(_TRI_RE.sub(lambda mm: _PAT_CODE[mm.group(0)], codes))
        else:
            parts.append(run.encode("ascii"))
    parts.append(_wrap_raw(text[prev:].encode("utf-8")))
    return b"".join(parts)


def decode_text_layer(data: bytes) -> bytes:
    """Конечный автомат: <0x80 литерал; 0x80-0xA0 строчная; 0xA1-0xC1 заглавная;
    0xC2-0xF5 триграмма; 0xFF RAW-блок; остальное — ошибка."""
    out = bytearray()
    i = 0
    n = len(data)
    while i < n:
        b = data[i]
        if b == 0xFF:
            if i + 2 > n or data[i + 1] == 0 or i + 2 + data[i + 1] > n:
                raise ValueError("повреждённый RAW-блок текстового яруса")
            ln = data[i + 1]
            out += data[i + 2:i + 2 + ln]
            i += 2 + ln
            continue
        if b <= 0x7F:
            out.append(b)
            i += 1
            continue
        if b <= 0xA0:
            out += CYR[b - 0x80].encode("utf-8")
            i += 1
            continue
        if b <= 0xC1:
            out += CYR[b - 0xA1].upper().encode("utf-8")
            i += 1
            continue
        if b <= 0xF5 and bytes([b]) in _TRI_INV:
            out += _TRI_INV[bytes([b])].encode("utf-8")
            i += 1
            continue
        raise ValueError("недопустимый код текстового яруса")
    return bytes(out)
