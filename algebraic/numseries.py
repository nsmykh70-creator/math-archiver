"""Кодек журнала состояний: x0, затем только шаги (+k, -k, *k, /k).

Полный журнал хранит каждую строку целиком (a + k = b), причём a — это
результат предыдущей строки. Достаточно затравки и последовательности
шагов: каждый новый итог восстанавливается применением операции.

Снапшоты ('=значение') вставляются каждые snapshot_every шагов: дают
случайный доступ и локализуют повреждение бита (как checkpoint в WAL).
Декодер использует их для синхронизации, но НЕ выводит в результат.

Строки вне цепочки хранятся дословно с префиксом '!' — без потерь.
"""
import re

from .kinds import BARE_NUM_RE, NUM_STEP_RE


def _apply(a: int, op: str, k: int):
    if op == "+":
        return a + k
    if op == "-":
        return a - k
    if op == "*":
        return a * k
    return a // k if k and a % k == 0 else None


def _canonical(m) -> bool:
    for i in (1, 3, 4):
        if m.group(i) != str(int(m.group(i))):
            return False
    return True


def compact_journal(text: str, snapshot_every: int = 0) -> str:
    out = []
    prev = None
    steps = 0
    for ln in text.split("\n"):
        if not ln:
            out.append(ln)
            continue
        m = NUM_STEP_RE.match(ln)
        if m and _canonical(m):
            a, op, k, c = int(m.group(1)), m.group(2), int(m.group(3)), int(m.group(4))
            if prev is None:
                # Первая строка-шаг без затравки: храним дословно, она задаёт состояние.
                out.append("!" + ln)
                prev = c
                continue
            if a == prev and _apply(a, op, k) == c:
                out.append(op + m.group(3))
                steps += 1
                if snapshot_every and steps % snapshot_every == 0:
                    out.append("=" + str(c))
                prev = c
                continue
            out.append("!" + ln)
            prev = c
            continue
        if BARE_NUM_RE.match(ln) and ln == str(int(ln)):
            prev = int(ln)
            out.append(ln)
            continue
        out.append("!" + ln)
    return "\n".join(out)


def rebuild_from_deltas(text: str) -> str:
    out = []
    prev = None
    for ln in text.split("\n"):
        if not ln:
            out.append(ln)
            continue
        if ln.startswith("="):  # снапшот: синхронизация, не выводится
            if prev is None:
                raise ValueError("снапшот до затравки")
            prev = int(ln[1:])
            continue
        if ln.startswith("!"):
            raw = ln[1:]
            out.append(raw)
            m = NUM_STEP_RE.match(raw)
            if m:
                prev = int(m.group(4))
            elif BARE_NUM_RE.match(raw) and raw == str(int(raw)):
                prev = int(raw)
            continue
        if BARE_NUM_RE.match(ln) and ln == str(int(ln)):  # затравка
            prev = int(ln)
            out.append(ln)
            continue
        if prev is None:
            raise ValueError("шаг до затравки")
        op = ln[0]
        k = int(ln[1:])
        b = _apply(prev, op, k)
        if b is None:
            raise ValueError(f"повреждённый шаг: {ln!r}")
        out.append(f"{prev}{op}{k}={b}")
        prev = b
    return "\n".join(out)
