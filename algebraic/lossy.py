"""ПОТЕРЬНЫЙ «скелет» текста — демонстрация слоя 2 для режима mode>=2.

ВНИМАНИЕ: обратного преобразования НЕТ. Функции существуют, чтобы показать
верхнюю оценку выигрыша «скелета» (гласные/огласовки убираются там, где слово
остаётся узнаваемым). Контейнер algebraic их НИКОГДА не вызывает: весь
основной конвейер строго без потерь. Используйте только если данные можно
портить (поисковый индекс, черновики, ключевые слова).
"""
import os

RU_VOWELS = set("аеёиоуыэюяАЕЁИОУЫЭЮЯ")
EN_VOWELS = set("aeiouyAEIOUY")
# Арабские огласовки (харакаты) — в быту и так опускаются.
AR_DIACRITICS = set(range(0x064B, 0x0653))
PUNCT = ",.!?;:«»\"'()"


def skeleton_word(word: str, min_len: int = 4) -> str:
    core = word.strip(PUNCT)
    if len(core) < min_len:
        return word  # короткие слова (предлоги, союзы) не трогаем
    return "".join(
        ch for ch in word
        if ch not in RU_VOWELS and ch not in EN_VOWELS and ord(ch) not in AR_DIACRITICS
    )


def skeleton_text(text: str, min_len: int = 4) -> str:
    """Скелет: только согласный костяк длинных слов. Без гарантий восстановления."""
    return " ".join(skeleton_word(w, min_len) for w in text.split(" "))
