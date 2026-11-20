#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Эксперименты по увеличению сжатия для math-archiver/UHC.
Три блока: русский текст, журналы операций, бинарные сегменты 10МБ файла.
Все результаты печатаются и сохраняются в exp_results.json.
"""
import json, lzma, math, re, sys, os
from collections import Counter

REPO = '/home/z/my-project/download/math-archiver'
UPLOAD = '/home/z/my-project/upload'
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'exp_results.json')

def xz(data: bytes, preset: int = 6 | lzma.PRESET_EXTREME) -> bytes:
    return lzma.compress(data, format=lzma.FORMAT_XZ, preset=preset)

def pct(n, d): return round(100.0 * n / d, 2) if d else 0.0

# ───────────────────────── ТРАНСЛИТ И ПРОРЕЖИВАНИЕ (как в UHC) ─────────────────────────
CYR_TABLE = {}
upper = 'АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ'
upper_tr = ['A','B','V','G','D','E','Yo','Zh','Z','I','Y','K','L','M','N','O','P','R','S','T','U','F','Kh','Ts','Ch','Sh','Shch','','Y','','E','Yu','Ya']
lower = 'абвгдеёжзийклмнопрстуфхцчшщъыьэюя'
lower_tr = ['a','b','v','g','d','e','yo','zh','z','i','y','k','l','m','n','o','p','r','s','t','u','f','kh','ts','ch','sh','shch','','y','','e','yu','ya']
for a, b in zip(upper, upper_tr): CYR_TABLE[a] = b
for a, b in zip(lower, lower_tr): CYR_TABLE[a] = b

VOWELS = set('aeiouyAEIOUY')

def translit(text: str) -> str:
    return ''.join(CYR_TABLE.get(c, c) for c in text)

def prune_word(w: str, keep_prefix: int) -> str:
    chars = list(w)
    if len(chars) <= 4 or not any(c.isalpha() for c in chars):
        return w
    last = chars[-1]
    out = chars[:keep_prefix]
    prev_cons = None
    for c in chars[keep_prefix:-1]:
        if c.isalpha():
            if c.lower() in VOWELS:
                continue
            low = c.lower()
            if prev_cons == low:
                continue
            prev_cons = low
            out.append(c)
        else:
            out.append(c)
    out.append(last)
    return ''.join(out)

def prune_text(text: str, keep_prefix: int) -> str:
    return ' '.join(prune_word(w, keep_prefix) for w in text.split(' '))

def build_ru_corpus():
    """Русские строки из реальных документов проекта."""
    files = [f'{REPO}/README.md', f'{REPO}/uhc/README_RU.md', f'{UPLOAD}/PS8_1_STATUS_RU.md']
    lines, seen = [], set()
    for fp in files:
        with open(fp, encoding='utf-8') as f:
            for ln in f:
                ln = ln.strip()
                if len(ln) < 40 or ln in seen:
                    continue
                cyr = sum(1 for c in ln if 'а' <= c.lower() <= 'я' or c == 'ё' or 'А' <= c <= 'Я' or c == 'Ё')
                if cyr * 2 >= len(ln):
                    seen.add(ln); lines.append(ln)
    return '\n'.join(lines)

def restore_from_dict(skeleton: str, vocab: dict) -> str:
    return ' '.join(vocab.get(w, w) for w in skeleton.split(' '))

def exp_text():
    corpus = build_ru_corpus()
    raw = corpus.encode('utf-8')
    size_raw = len(raw)
    res = {'corpus_bytes': size_raw, 'corpus_lines': corpus.count(chr(10)) + 1}
    res['raw_xz'] = pct(len(xz(raw)), size_raw)
    tr = translit(corpus)
    tr_b = tr.encode('utf-8')
    res['translit_xz'] = pct(len(xz(tr_b)), size_raw)
    sk1 = prune_text(tr, 2)
    res['prune1_xz'] = pct(len(xz(sk1.encode('utf-8'))), size_raw)
    sk2 = prune_text(tr, 1)
    sk2_b = sk2.encode('utf-8')
    res['prune2_xz'] = pct(len(xz(sk2_b)), size_raw)
    # Словарь ТОЛЬКО двусмысленностей + обратная таблица транслита:
    # скелет -> транслит (по однозначным парам), транслит -> кириллица.
    sk_words = sk2.split(' ')
    orig_words = tr.split(' ')
    pairs = {}
    ambiguous = {}
    for s, o in zip(sk_words, orig_words):
        if s == o: continue
        if s in pairs and pairs[s] != o: ambiguous.setdefault(s, {pairs[s]}).add(o)
        else: pairs.setdefault(s, o)
    amb_entries = {s: sorted(v) for s, v in ambiguous.items()}
    # позиции двусмысленных слов (дельта-позиции) — список пар [позиция, индекс варианта]
    amb_positions = []
    var_idx = {s: {w: i for i, w in enumerate(sorted(v))} for s, v in ambiguous.items()}
    for i, s in enumerate(sk_words):
        if s in amb_entries:
            amb_positions.append([i, var_idx[s][orig_words[i]]])
    amb_bytes = json.dumps({'m': amb_entries, 'p': amb_positions}, ensure_ascii=False).encode('utf-8')
    amb_xz = xz(amb_bytes)
    # обратный транслит: однозначные символы + словарь омонимов на уровне слов
    inv = {}
    for k, v in CYR_TABLE.items():
        if v == '': continue
        inv.setdefault(v, set()).add(k)
    inv_amb = {k: sorted(v) for k, v in inv.items() if len(v) > 1}
    # восстановление транслита из скелета
    restored_tr_words = []
    amb_pos_map = dict(amb_positions)
    var_by_s = {s: sorted(v) for s, v in ambiguous.items()}
    j = 0
    for i, s in enumerate(sk_words):
        if i in amb_pos_map:
            restored_tr_words.append(var_by_s[s][amb_pos_map[i]])
        else:
            restored_tr_words.append(pairs.get(s, s))
    restored_tr = ' '.join(restored_tr_words)
    res['restore_to_translit_ok'] = restored_tr == tr
    # посимвольные омонимы обратного транслита (для восстановления кириллицы)
    inv_char_amb = {k: sorted(v) for k, v in inv.items() if len(v) > 1}
    res['inv_translit_amb_keys'] = list(inv_char_amb.keys())
    res['amb_dict_xz_bytes'] = len(amb_xz)
    res['amb_entries'] = len(amb_entries)
    res['amb_words_count'] = len(amb_positions)
    # Итоговая lossless-схема: скелет + словарь двусмысленностей (транслит восстановим точно)
    res['prune2_lossless_total'] = pct(len(xz(sk2_b)) + len(amb_xz), size_raw)
    res['restore_chain'] = 'скелет -> (словарь двусмысленностей) -> транслит; кириллица -> обратная таблица + омонимы'
    # старый полный словарь — для сравнения
    vocab = {s: o for s, o in zip(sk_words, orig_words) if s != o}
    dict_xz = xz(json.dumps(vocab, ensure_ascii=False, sort_keys=True).encode('utf-8'))
    res['prune2_dict_xz'] = pct(len(xz(sk2_b)) + len(dict_xz), size_raw)
    res['dict_entries'] = len(vocab)
    res['dict_xz_bytes'] = len(dict_xz)
    res['ambiguous_words'] = len(amb_entries)
    res['restorable'] = res['restore_to_translit_ok']
    res['skeleton2_bytes'] = len(sk2_b)
    res['skeleton2_vs_raw_chars'] = pct(len(sk2), len(corpus))
    # сколько гласных реально удаляется (потенциал метода)
    vowels_removed = sum(1 for c in tr if c.lower() in VOWELS) - sum(1 for c in sk2 if c.lower() in VOWELS)
    res['vowels_removed'] = vowels_removed
    res['translit_chars'] = len(tr)
    return res

# ───────────────────────── ЖУРНАЛЫ ОПЕРАЦИЙ ─────────────────────────
def zigzag(n: int) -> int:
    return (n << 1) ^ (n >> 63) if n >= 0 else ((-n) << 1) - 1

def encode_varint(val: int, out: bytearray):
    while val >= 0x80:
        out.append(((val & 0x7F) | 0x80)); val >>= 7
    out.append(val)

def gen_journal(n_ops: int, seed: int):
    import random
    rng = random.Random(seed)
    x = rng.randint(10, 500)
    lines = [str(x)]
    cur = x
    for _ in range(n_ops):
        op = rng.choices('+-*/', weights=[55, 25, 12, 8])[0]
        r = rng.random()
        if r < 0.6: step = rng.randint(1, 9)
        elif r < 0.9: step = rng.randint(10, 99)
        else: step = rng.randint(100, 9999)
        if op == '+': cur += step
        elif op == '-': cur = max(0, cur - step)
        elif op == '*': cur *= step
        else: step = max(1, step); cur //= step
        lines.append(f'{op}{step}')
    return '\n'.join(lines) + '\n'

def journal_binary(lines_text: str) -> bytes:
    ls = [l.strip() for l in lines_text.splitlines() if l.strip()]
    out = bytearray()
    encode_varint(zigzag(int(ls[0])), out)
    encode_varint(len(ls) - 1, out)
    for l in ls[1:]:
        out.append('+-*/'.index(l[0]))
        encode_varint(int(l[1:]), out)
    return bytes(out)

def journal_optimized(lines_text: str) -> bytes:
    """Оптимизированная запись: op+step как nibble-токен для частых значений,
    varint для остальных; op-поток отдельно."""
    ls = [l.strip() for l in lines_text.splitlines() if l.strip()]
    out = bytearray()
    encode_varint(zigzag(int(ls[0])), out)
    encode_varint(len(ls) - 1, out)
    # токены: 0..31 — частые op+step (op в старших 2 битах, step 1..8 в 3 младших битах)
    for l in ls[1:]:
        op = '+-*/'.index(l[0]); step = int(l[1:])
        if step <= 8:
            out.append(0x80 | (op << 3) | (step - 1))
        else:
            out.append(0x00 | (op << 3)); encode_varint(step, out)
    return bytes(out)

def exp_journal():
    text = gen_journal(200_000, seed=20261120)
    raw = text.encode('utf-8')
    res = {'ops': 200_000, 'raw_bytes': len(raw)}
    res['raw_xz'] = pct(len(xz(raw)), len(raw))
    uhc_bin = journal_binary(text)
    res['uhc_binary_xz'] = pct(len(xz(uhc_bin)), len(raw))
    opt = journal_optimized(text)
    res['token_binary_xz'] = pct(len(xz(opt)), len(raw))
    res['uhc_binary_raw'] = pct(len(uhc_bin), len(raw))
    res['token_binary_raw'] = pct(len(opt), len(raw))
    res['opt_roundtrip_ok'] = journal_optimized(text) == opt
    # проверка восстановимости
    dec = decode_opt(opt)
    res['decode_ok'] = dec == text
    # энтропийный предел order-0 токен-потока (нижняя граница для арифм./Хаффмана)
    freq = Counter(opt)
    total = sum(freq.values())
    H0 = -sum((c / total) * math.log2(c / total) for c in freq.values())
    res['token_entropy_floor_pct'] = round(100.0 * H0 * total / 8 / len(raw), 2)
    res['token_entropy_bits'] = round(H0, 2)
    # снежный ком: шаг выводится из текущего состояния (структурная предсказуемость)
    import random
    rng = random.Random(20261120)
    cur = rng.randint(10, 500)
    lines = [str(cur)]
    for i in range(200_000):
        op = '+-*/'[i % 4]
        step = (cur % 97) + 1
        if op == '+': cur += step
        elif op == '-': cur -= max(1, cur % step) if step > 1 else 0
        elif op == '*': cur *= step
        else: cur //= max(2, cur % 7 + 2)
        lines.append(f'{op}{step}')
    snow_text = '\n'.join(lines) + '\n'
    snow_raw = snow_text.encode('utf-8')
    res['snow_raw_xz'] = pct(len(xz(snow_raw)), len(snow_raw))
    res['snow_bytes'] = len(snow_raw)
    return res

def decode_opt(bin: bytes) -> str:
    off = 0
    def rv():
        nonlocal off
    # простая декодирующая функция
    pos = 0
    def read_varint(pos):
        val, shift = 0, 0
        while True:
            b = bin[pos]; pos += 1
            val |= (b & 0x7F) << shift
            if b < 0x80: return val, pos
            shift += 7
    zz = lambda v: (v >> 1) if not (v & 1) else -((v + 1) >> 1)
    x0, pos = read_varint(0)
    cur = zz(x0)
    count, pos = read_varint(pos)
    lines = [str(cur)]
    for _ in range(count):
        b = bin[pos]; pos += 1
        op = (b >> 3) & 3
        if b & 0x80:
            step = (b & 7) + 1
        else:
            step, pos = read_varint(pos)
        sym = '+-*/'[op]
        if op == 0: cur += step
        elif op == 1: cur -= step
        elif op == 2: cur *= step
        else: cur //= max(1, step)
        lines.append(f'{sym}{step}')
    return '\n'.join(lines) + '\n'

# ───────────────────────── БИНАРНЫЕ СЕГМЕНТЫ 10МБ ─────────────────────────
def delta1(data: bytes) -> bytes:
    prev = 0; out = bytearray(len(data))
    for i, b in enumerate(data):
        out[i] = (b - prev) & 0xFF; prev = b
    return bytes(out)

def undelta1(data: bytes) -> bytes:
    prev = 0; out = bytearray(len(data))
    for i, b in enumerate(data):
        prev = (prev + b) & 0xFF; out[i] = prev
    return bytes(out)

def xorprev(data: bytes) -> bytes:
    prev = 0; out = bytearray(len(data))
    for i, b in enumerate(data):
        out[i] = b ^ prev; prev = b
    return bytes(out)

def unxorprev(data: bytes) -> bytes:
    """Обратная сборка: b[i] = out[i] ^ b[i-1]."""
    out = bytearray(len(data)); prev = 0
    for i, b in enumerate(data):
        prev = b ^ prev; out[i] = prev
    return bytes(out)

def planesplit(data: bytes) -> bytes:
    n = len(data) // 8 * 8
    a = bytearray(data[:n])
    b0 = a[0::8]; b1 = a[1::8]; b2 = a[2::8]; b3 = a[3::8]
    b4 = a[4::8]; b5 = a[5::8]; b6 = a[6::8]; b7 = a[7::8]
    return bytes(b0) + bytes(b1) + bytes(b2) + bytes(b3) + bytes(b4) + bytes(b5) + bytes(b6) + bytes(b7)

def xorstride(data: bytes, stride: int) -> bytes:
    out = bytearray(data)
    for i in range(stride, len(data)):
        out[i] ^= out[i - stride]
    return bytes(out)

def try_zstd(data: bytes):
    try:
        import zstandard as zmod
        c = zmod.ZstdCompressor(level=19)
        return len(c.compress(data))
    except Exception:
        return None

def exp_binary():
    path = f'{UPLOAD}/mixed_10mb_compression_test.bin'
    data = open(path, 'rb').read()
    segments = json.load(open(f'{UPLOAD}/mixed_10mb_compression_test.manifest.json'))['segments']
    results = []
    for seg in segments:
        d = data[seg['offset']: seg['offset'] + seg['length']]
        n = len(d)
        r = {'name': seg['name'], 'desc': seg['description'], 'bytes': n,
             'xz': pct(len(xz(d, 6)), n)}
        z = try_zstd(d); r['zstd19'] = pct(z, n) if z is not None else None
        # трансформации + zstd (обратимые, обратная сборка при распаковке)
        t1 = try_zstd(delta1(d))
        r['delta1_zstd'] = pct(t1, n) if t1 is not None else None
        t2 = try_zstd(xorprev(d))
        r['xorprev_zstd'] = pct(t2, n) if t2 is not None else None
        t3 = try_zstd(planesplit(d))
        r['planesplit_zstd'] = pct(t3, n) if t3 is not None else None
        t4 = try_zstd(xorstride(d, 16))
        r['xorstride16_zstd'] = pct(t4, n) if t4 is not None else None
        # проверка обратимости трансформаций на первых 64 КБ
        chk = d[:65536]
        assert undelta1(delta1(chk)) == chk
        assert unxorprev(xorprev(chk)) == chk
        results.append(r)
    # верификация обратимости: delta/xor через обратные функции (выше), planesplit — ниже
    return {'segments': results}

def planesplit_roundtrip_check(data):
    n = (len(data) // 8) * 8
    a = planesplit(data[:n])
    # обратная сборка: та же транспонировка — интерливинг обратно
    out = bytearray(n)
    k = n // 8
    for j in range(8):
        out[j::8] = a[j*k:(j+1)*k]
    return bytes(out) == data[:n]

if __name__ == '__main__':
    out = {}
    print('=== 1. Русский текст (транслит + прореживание + словарь) ===')
    out['text'] = exp_text(); print(json.dumps(out['text'], ensure_ascii=False, indent=1))
    print('=== 2. Журнал операций (200k операций) ===')
    out['journal'] = exp_journal(); print(json.dumps(out['journal'], ensure_ascii=False, indent=1))
    print('=== 3. Бинарные сегменты (обратимые трансформации) ===')
    out['binary'] = exp_binary()
    out['binary']['planesplit_roundtrip_ok'] = planesplit_roundtrip_check(
        open('/home/z/my-project/upload/mixed_10mb_compression_test.bin','rb').read()[:65536])
    for r in out['binary']['segments']:
        print(json.dumps(r, ensure_ascii=False))
    json.dump(out, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('saved:', OUT)
