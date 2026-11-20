"""CRC-16/CCITT-FALSE: полином 0x1021, init 0xFFFF, без отражения, xorout 0.

Используется как трейлер кадра MAF2 (2 байта, big-endian) поверх заголовка
и нагрузки: порча ЛЮБОГО байта кадра, кроме самих байтов CRC, обнаруживается
на входе декодера до всякой распаковки. Реализация — binascii.crc_hqx
(та же CRC на скорости C); в тестах есть независимая табличная проверка
(контрольное значение для «123456789» — 0x29B1).
"""
import binascii


def crc16_ccitt(data: bytes, crc: int = 0xFFFF) -> int:
    """CRC-16/CCITT-FALSE от data с начальным регистром crc."""
    return binascii.crc_hqx(data, crc)
