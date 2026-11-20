"""Контейнер MAF1: авто-выбор формулы + двухступенчатое сжатие.

Реализация псевдокода compress_block / decompress_block из концепции:

  compress_block(block, mode):   detect_kind -> формула -> LZMA2 -> проверка
  decompress_block(frame):       заголовок -> LZMA2 -> обратная формула

Формат заголовка (14 байт):
  MAGIC 'MAF1' (4) | kind (1) | flags (1) | orig_len (8, big-endian)

flags: 0 — сохранено как есть; 1 — xz(LZMA2); 2 — формула (кодек);
       3 — формула + xz (двухступенчатая связка, слой 2 + слой 3).

Каждый кандидат перед выбором проверяется обратным преобразованием:
если хотя бы байт не совпал — кандидат отбрасывается. Результат всегда
побайтово равен исходнику (без потерь).
"""
import lzma
import struct

from .kinds import detect_kind
from . import numeq, numseries, textcodec

MAGIC = b"MAF1"
HEADER_LEN = 14
KIND_IDS = {"BIN": 0, "NUM_EQ": 1, "NUM_SERIES": 2, "ALPHA_TEXT": 3, "TEXT_IDEO": 4}
ID_KINDS = {v: k for k, v in KIND_IDS.items()}

_XZ_FILTERS = [{"id": lzma.FILTER_LZMA2, "preset": 6}]


def _xz(data: bytes) -> bytes:
    return lzma.compress(data, format=lzma.FORMAT_RAW, filters=_XZ_FILTERS)


def _unxz(data: bytes) -> bytes:
    return lzma.decompress(data, format=lzma.FORMAT_RAW, filters=_XZ_FILTERS)


def _codec_encode(kind: str, data: bytes, snapshot_every: int = 0) -> bytes:
    text = data.decode("utf-8")
    if kind == "NUM_EQ":
        return numeq.compact_equations(text).encode("utf-8")
    if kind == "NUM_SERIES":
        return numseries.compact_journal(text, snapshot_every=snapshot_every).encode("utf-8")
    if kind in ("ALPHA_TEXT", "TEXT_IDEO"):
        return textcodec.prune_text(text)
    return data


def _codec_decode(kind: str, data: bytes) -> bytes:
    if kind == "NUM_EQ":
        return numeq.solve_missing_parts(data.decode("utf-8")).encode("utf-8")
    if kind == "NUM_SERIES":
        return numseries.rebuild_from_deltas(data.decode("utf-8")).encode("utf-8")
    if kind in ("ALPHA_TEXT", "TEXT_IDEO"):
        return textcodec.restore_text(data).encode("utf-8")
    return data


def _frame(kind_id: int, flag: int, blob: bytes, orig_len: int) -> bytes:
    return MAGIC + bytes((kind_id, flag)) + struct.pack(">Q", orig_len) + blob


def compress_bytes(data: bytes, snapshot_every: int = 0) -> bytes:
    """Сжать байты; результат побайтово обратим (проверяется перед записью)."""
    kind = detect_kind(data)
    kind_id = KIND_IDS[kind]
    candidates = [(0, data)]
    try:
        candidates.append((1, _xz(data)))
    except Exception:
        pass
    if kind != "BIN":
        try:
            packed = _codec_encode(kind, data, snapshot_every)
            candidates.append((2, packed))
            candidates.append((3, _xz(packed)))
        except Exception:
            pass
    best = None
    for flag, blob in candidates:
        try:
            back = decompress_bytes(_frame(kind_id, flag, blob, len(data)))
            if back != data:
                continue
        except Exception:
            continue
        if best is None or len(blob) < len(best[1]):
            best = (flag, blob)
    if best is None:  # вариант 0 всегда корректен — сюда дойти не должно
        best = (0, data)
    return _frame(kind_id, best[0], best[1], len(data))


def decompress_bytes(frame: bytes) -> bytes:
    if len(frame) < HEADER_LEN or frame[:4] != MAGIC:
        raise ValueError("не контейнер MAF1")
    kind = ID_KINDS.get(frame[4])
    flag = frame[5]
    if kind is None or flag not in (0, 1, 2, 3):
        raise ValueError("повреждённый заголовок MAF1")
    (orig_len,) = struct.unpack(">Q", frame[6:HEADER_LEN])
    body = frame[HEADER_LEN:]
    if flag & 1:
        body = _unxz(body)
    if flag & 2:
        body = _codec_decode(kind, body)
    if len(body) != orig_len:
        raise ValueError("размер не совпал — контейнер повреждён")
    return body


def detect_kind_of(data: bytes) -> str:
    """Публичный алиас для CLI."""
    return detect_kind(data)
