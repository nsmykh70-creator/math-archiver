"""Определение типа данных: BIN | NUM_EQ | NUM_SERIES | ALPHA_TEXT | TEXT_IDEO."""
import re
import unicodedata

NUM_EQ_RE = re.compile(r"^(\d+)([+\-*/^])(\d+)=(\d+)$")
NUM_STEP_RE = re.compile(r"^(\d+)([+\-*/])(\d+)=(\d+)$")
BARE_NUM_RE = re.compile(r"^\d+$")


def _apply(a: int, op: str, k: int):
    """Применить шаг; None — если операция не даёт точного целого."""
    if op == "+":
        return a + k
    if op == "-":
        return a - k
    if op == "*":
        return a * k
    if op == "/":
        return a // k if k and a % k == 0 else None
    return None


def _canonical(m) -> bool:
    """Числа без ведущих нулей (иначе строка не канонична и уйдёт в escape)."""
    for i in (1, 3, 4):
        if m.group(i) != str(int(m.group(i))):
            return False
    return True


def _looks_like_chain(lines) -> bool:
    """Журнал состояний: a_i == результат предыдущей строки."""
    prev = None
    hits = 0
    total = 0
    for ln in lines:
        total += 1
        m = NUM_STEP_RE.match(ln)
        if m and _canonical(m):
            a, op, k, c = int(m.group(1)), m.group(2), int(m.group(3)), int(m.group(4))
            if prev is None or a == prev:
                if _apply(a, op, k) == c:
                    prev = c
                    hits += 1
                    continue
            prev = None
            continue
        if BARE_NUM_RE.match(ln) and ln == str(int(ln)):
            prev = int(ln)
            hits += 1
            continue
        prev = None
    return total > 0 and hits >= 0.9 * total


def detect_kind(data: bytes) -> str:
    """BIN (не UTF-8), NUM_EQ (независимые равенства), NUM_SERIES (журнал
    состояний — цепочка), ALPHA_TEXT / TEXT_IDEO (текст любой письменности)."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return "BIN"
    lines = [ln for ln in text.split("\n") if ln]
    if not lines:
        return "ALPHA_TEXT"
    sample = lines[:5000]
    eq_hits = sum(1 for ln in sample if NUM_EQ_RE.match(ln))
    if eq_hits >= 0.9 * len(sample):
        # Журнал — это тоже строки «a op b = c», но сцепленные в цепочку:
        # различаем по свойству a_i == результату предыдущей строки.
        return "NUM_SERIES" if _looks_like_chain(sample) else "NUM_EQ"
    letters = ideographs = 0
    for ch in text[:200000]:
        cat = unicodedata.category(ch)
        if cat.startswith("L"):
            letters += 1
            if "\u3040" <= ch <= "\u30ff" or "\u4e00" <= ch <= "\u9fff" or "\uac00" <= ch <= "\ud7af":
                ideographs += 1
    if letters and ideographs / letters > 0.3:
        return "TEXT_IDEO"
    return "ALPHA_TEXT"
