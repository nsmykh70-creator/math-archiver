"""Контейнер MAF1/MAF2: авто-выбор формулы + двухступенчатое сжатие.

MAF1 (чтение для совместимости): MAGIC 'MAF1'(4) | kind(1) | flags(1) |
orig_len(8, big-endian); flags: 0 — как есть, 1 — xz(LZMA2), 2 — формула,
3 — формула + xz.

MAF2 (запись): MAGIC 'MAF2'(4) | kind(1) | flags(1) | orig_len(8 BE) |
backend(1) | payload | CRC-16/CCITT (2, big-endian) над header+payload.
Биты flags: 1 — словесно-формульный слой; 2 — varint-упаковка длинных
чисел; 4 — нагрузка сжата; 8 — текстовый ярус textlayer (V-byte) вместо
textcodec. backend: 0 = xz (LZMA2, preset 6), 1 = zstd (уровень 3),
2 = gzip (уровень 6, mtime=0 — детерминированный вывод).

Конвейер записи: данные -> [формула] -> [varint] -> [сжатие]; чтение — в
обратном порядке. CRC покрывает заголовок и нагрузку, поэтому порча любого
байта кадра (кроме самих байтов CRC) обнаруживается до распаковки. Каждый
кандидат проверяется обратным преобразованием; из проверённых берётся
самый короткий — результат всегда побайтово равен исходнику.
"""
import gzip as _gzip
import lzma
import struct

try:
    import zstandard as _zstd
except ImportError:  # пакет опционален: нужен только для backend="zstd"
    _zstd = None

from . import crc16, numeq, numseries, textcodec, textlayer, varint
from .kinds import detect_kind

MAGIC = b"MAF1"
MAGIC2 = b"MAF2"
HEADER_LEN = 14   # MAF1
HEADER2_LEN = 15  # MAF2

FLAG_CODEC = 1
FLAG_VARINT = 2
FLAG_COMP = 4
FLAG_TLAYER = 8
_FLAG_MASK = FLAG_CODEC | FLAG_VARINT | FLAG_COMP | FLAG_TLAYER

BACKEND_IDS = {"xz": 0, "zstd": 1, "gzip": 2}
ID_BACKENDS = {v: k for k, v in BACKEND_IDS.items()}

KIND_IDS = {"BIN": 0, "NUM_EQ": 1, "NUM_SERIES": 2, "ALPHA_TEXT": 3, "TEXT_IDEO": 4}
ID_KINDS = {v: k for k, v in KIND_IDS.items()}

_XZ_FILTERS = [{"id": lzma.FILTER_LZMA2, "preset": 6}]


def _compress(data: bytes, backend: str) -> bytes:
    if backend == "xz":
        return lzma.compress(data, format=lzma.FORMAT_RAW, filters=_XZ_FILTERS)
    if backend == "zstd":
        if _zstd is None:
            raise RuntimeError("backend zstd требует пакет zstandard")
        return _zstd.ZstdCompressor(level=3).compress(data)
    if backend == "gzip":
        return _gzip.compress(data, compresslevel=6, mtime=0)
    raise ValueError(f"неизвестный backend: {backend!r}")


def _decompress(data: bytes, backend: str) -> bytes:
    if backend == "xz":
        return lzma.decompress(data, format=lzma.FORMAT_RAW, filters=_XZ_FILTERS)
    if backend == "zstd":
        if _zstd is None:
            raise RuntimeError("backend zstd требует пакет zstandard")
        return _zstd.ZstdDecompressor().decompress(data)
    if backend == "gzip":
        return _gzip.decompress(data)
    raise ValueError(f"неизвестный backend: {backend!r}")


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
    """Кадр MAF1 (совместимость)."""
    return MAGIC + bytes((kind_id, flag)) + struct.pack(">Q", orig_len) + blob


def _frame2(kind_id: int, flags: int, backend: str, blob: bytes,
            orig_len: int) -> bytes:
    """Кадр MAF2: header + payload + CRC-16(header+payload)."""
    head = (MAGIC2 + bytes((kind_id, flags, BACKEND_IDS[backend]))
            + struct.pack(">Q", orig_len))
    return head + blob + struct.pack(">H", crc16.crc16_ccitt(head + blob))


def compress_bytes(data: bytes, snapshot_every: int = 0, backend: str = "xz") -> bytes:
    """Сжать байты кадром MAF2; результат побайтово обратим (проверяется
    перед записью). backend: 'xz' (LZMA2), 'zstd' или 'gzip'."""
    if backend not in BACKEND_IDS:
        raise ValueError(f"неизвестный backend: {backend!r}")
    kind = detect_kind(data)
    kind_id = KIND_IDS[kind]

    # базовые варианты: (flags, payload без сжатия)
    bases = [(0, data)]
    if kind != "BIN":
        try:
            bases.append((FLAG_CODEC, _codec_encode(kind, data, snapshot_every)))
        except Exception:
            pass
        if kind == "ALPHA_TEXT":
            try:
                bases.append((FLAG_CODEC | FLAG_TLAYER,
                              textlayer.encode_text_layer(data)))
            except Exception:
                pass
        for i in range(len(bases)):
            try:
                packed = varint.encode_digits(bases[i][1])
            except Exception:
                packed = None
            if packed is not None:
                bases.append((bases[i][0] | FLAG_VARINT, packed))

    candidates = []
    for flags, payload in bases:
        candidates.append((flags, payload))
        if payload:
            try:
                candidates.append((flags | FLAG_COMP, _compress(payload, backend)))
            except Exception:
                pass
    candidates.sort(key=lambda c: len(c[1]))
    for flags, blob in candidates:
        frame = _frame2(kind_id, flags, backend, blob, len(data))
        try:
            if decompress_bytes(frame) == data:
                return frame
        except Exception:
            continue
    return _frame2(kind_id, 0, backend, data, len(data))


def _decode_maf1(frame: bytes) -> bytes:
    kind = ID_KINDS.get(frame[4])
    flag = frame[5]
    if kind is None or flag not in (0, 1, 2, 3):
        raise ValueError("повреждённый заголовок MAF1")
    (orig_len,) = struct.unpack(">Q", frame[6:HEADER_LEN])
    body = frame[HEADER_LEN:]
    if flag & 1:
        try:
            body = _unxz_maf1(body)
        except ValueError:
            raise
        except Exception:
            raise ValueError("повреждённая нагрузка MAF1") from None
    if flag & 2:
        try:
            body = _codec_decode(kind, body)
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError("повреждённая нагрузка MAF1") from None
    if len(body) != orig_len:
        raise ValueError("размер не совпал — контейнер повреждён")
    return body


def _unxz_maf1(data: bytes) -> bytes:
    return lzma.decompress(data, format=lzma.FORMAT_RAW, filters=_XZ_FILTERS)


def _decode_maf2(frame: bytes) -> bytes:
    if len(frame) < HEADER2_LEN + 2:
        raise ValueError("обрезанный кадр MAF2")
    kind = ID_KINDS.get(frame[4])
    flags = frame[5]
    backend = ID_BACKENDS.get(frame[6])
    if kind is None or backend is None or flags & ~_FLAG_MASK:
        raise ValueError("повреждённый заголовок MAF2")
    (orig_len,) = struct.unpack(">Q", frame[7:HEADER2_LEN])
    body = frame[HEADER2_LEN:-2]
    (stored,) = struct.unpack(">H", frame[-2:])
    if crc16.crc16_ccitt(frame[:HEADER2_LEN] + body) != stored:
        raise ValueError("CRC не сошёлся — контейнер повреждён")
    if flags & FLAG_COMP:
        try:
            body = _decompress(body, backend)
        except ValueError:
            raise
        except Exception:
            raise ValueError("не удалось распаковать нагрузку MAF2") from None
    if flags & FLAG_VARINT:
        body = varint.decode_digits(body)
    if flags & FLAG_CODEC:
        if flags & FLAG_TLAYER:
            body = textlayer.decode_text_layer(body)
        else:
            try:
                body = _codec_decode(kind, body)
            except ValueError:
                raise
            except Exception:
                raise ValueError("повреждённая нагрузка MAF2") from None
    if len(body) != orig_len:
        raise ValueError("размер не совпал — контейнер повреждён")
    return body


def decompress_bytes(frame: bytes) -> bytes:
    """Распаковать кадр MAF1 или MAF2; порча любого байта — ValueError."""
    if frame[:4] == MAGIC2:
        return _decode_maf2(frame)
    if len(frame) >= HEADER_LEN and frame[:4] == MAGIC:
        return _decode_maf1(frame)
    raise ValueError("не контейнер MAF1/MAF2")


def detect_kind_of(data: bytes) -> str:
    """Публичный алиас для CLI."""
    return detect_kind(data)
