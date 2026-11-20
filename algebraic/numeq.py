"""Кодек независимых равенств: a op b = c -> компактная форма.

Формы (все однозначно восстанавливаются строгой арифметикой):
  27*761      — неявный результат: c = a * b вычисляется;
  27*=20547   — неявный второй операнд: b = c / a (целочисленно);
  12-=9       — b = a - c;  80136/=106 — b = a / c;
  ^2=23415921 — неявное основание: целый корень из c;
  4839^2      — неявный результат степени.
Строки, не прошедшие проверку арифметики, хранятся дословно с префиксом
'!' — сжатие строго без потерь на любых входных данных.
"""
import re
from math import isqrt

from .kinds import NUM_EQ_RE

IROOT_RE = re.compile(r"^\^([23])=(\d+)$")
EXPL_RE = re.compile(r"^(\d+)\^([23])$")
OPD_RE = re.compile(r"^(\d+)([+\-*/])=(\d+)$")
IMPL_RE = re.compile(r"^(\d+)([+\-*/])(\d+)$")


def icbrt(n: int) -> int:
    """Целый кубический корень; -1, если n — не точный куб."""
    if n < 0:
        return -1
    x = int(round(n ** (1 / 3)))
    for cand in (x - 1, x, x + 1):
        if cand >= 0 and cand ** 3 == n:
            return cand
    return -1


def _canonical(m) -> bool:
    for i in (1, 3, 4):
        if m.group(i) != str(int(m.group(i))):
            return False
    return True


def _verify(a: int, op: str, b: int, c: int) -> bool:
    if op == "+":
        return a + b == c
    if op == "-":
        return a - b == c
    if op == "*":
        return a * b == c
    if op == "/":
        return b != 0 and a == b * c
    if op == "^":
        return b in (2, 3) and a ** b == c
    return False


def compact_line(line: str) -> str:
    """Одна строка -> компактная форма или '!'+строка (escape)."""
    if not line:
        return line
    m = NUM_EQ_RE.match(line)
    if not m or not _canonical(m):
        return "!" + line
    a, op, b, c = int(m.group(1)), m.group(2), int(m.group(3)), int(m.group(4))
    if not _verify(a, op, b, c):
        return "!" + line
    if op == "^":
        candidates = [f"{a}^{b}", f"^{b}={c}"]
    else:
        candidates = [f"{a}{op}{b}"]
        # Храним только первый операнд (+ результат): второй восстанавливается
        # обратной операцией. Обратный порядок дал бы другую строку при сборке.
        if op == "-":
            candidates.append(f"{a}-={c}")
        elif op == "/":
            if c != 0 and a % c == 0:
                candidates.append(f"{a}/={c}")
        else:  # '+' и '*': операнды симметричны, храним a
            if a != 0 and c % a == 0:
                candidates.append(f"{a}{op}={c}")
    return min(candidates, key=len)


def compact_equations(text: str) -> str:
    return "\n".join(compact_line(ln) for ln in text.split("\n"))


def solve_line(line: str) -> str:
    """Компактная строка -> исходное равенство."""
    if line.startswith("!"):
        return line[1:]
    if not line:
        return line
    m = IROOT_RE.match(line)
    if m:
        e, c = int(m.group(1)), int(m.group(2))
        root = isqrt(c) if e == 2 else icbrt(c)
        if root < 0 or root ** e != c:
            raise ValueError(f"повреждённая строка: {line!r}")
        return f"{root}^{e}={c}"
    m = EXPL_RE.match(line)
    if m:
        a, e = int(m.group(1)), int(m.group(2))
        return f"{a}^{e}={a ** e}"
    m = OPD_RE.match(line)
    if m:
        x, op, c = int(m.group(1)), m.group(2), int(m.group(3))
        if op == "*":
            if x == 0 or c % x:
                raise ValueError(f"повреждённая строка: {line!r}")
            y = c // x
        elif op == "+":
            y = c - x
            if y <= 0:
                raise ValueError(f"повреждённая строка: {line!r}")
        elif op == "-":
            y = x - c
            if y < 0:
                raise ValueError(f"повреждённая строка: {line!r}")
        else:  # '/'
            if c == 0 or x % c:
                raise ValueError(f"повреждённая строка: {line!r}")
            y = x // c
        return f"{x}{op}{y}={c}"
    m = IMPL_RE.match(line)
    if m:
        a, op, b = int(m.group(1)), m.group(2), int(m.group(3))
        if op == "/":
            if b == 0:
                raise ValueError(f"повреждённая строка: {line!r}")
            return f"{a}/{b}={a // b}"
        val = a + b if op == "+" else a - b if op == "-" else a * b
        return f"{a}{op}{b}={val}"
    raise ValueError(f"повреждённая строка: {line!r}")


def solve_missing_parts(text: str) -> str:
    return "\n".join(solve_line(ln) for ln in text.split("\n"))
