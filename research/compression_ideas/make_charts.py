#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Графики для отчёта «Идеи увеличения сжатия». Правила: charts.md
(горизонтальные бары для длинных подписей, без верхних/правых осей,
пунктирная сетка 20%, значения подписаны, легенда без рамки, без
внутренних заголовков — в PDF подписи-каптионы)."""
import json, os
import matplotlib
import matplotlib.font_manager as fm
fm.fontManager.addfont('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')
fm.fontManager.addfont('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf')
import matplotlib.pyplot as plt
plt.rcParams['font.sans-serif'] = ['DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

HERE = os.path.dirname(os.path.abspath(__file__))
RES = json.load(open(os.path.join(HERE, 'exp_results.json'), encoding='utf-8'))
OUT = os.path.join(HERE, 'charts')
os.makedirs(OUT, exist_ok=True)

# Палитра из palette.cascade
ACCENT   = '#907422'
ACCENT2  = '#6141c3'
HEADER   = '#504b3a'
ICON     = '#8c7c4a'
MUTED    = '#86837c'
TEXTC    = '#252422'
BORDER   = '#c5c0b2'
SEM_OK   = '#448359'

def style_ax(ax):
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_color(BORDER)
    ax.spines['bottom'].set_color(BORDER)
    ax.tick_params(colors=MUTED, labelsize=10)
    ax.xaxis.grid(True, linestyle='--', linewidth=0.5, alpha=0.2, color=HEADER)
    ax.set_axisbelow(True)
    ax.set_xlabel('Доля от исходника, % (меньше — лучше)', fontsize=10, color=MUTED)

# ── График 1: лестница сжатия русского текста ──
t = RES['text']
labels1 = [
    'Полный словарь + xz (анти-вариант)',
    'Исходник + xz (базовый)',
    'Транслит + xz',
    'Скелет 2 + xz (без восстановления)',
    'Скелет 2 + словарь двусмысленностей\n+xz (обратимая сборка)',
    'Скелет 1 + xz (без восстановления)',
]
vals1 = [t['prune2_dict_xz'], t['raw_xz'], t['translit_xz'],
         t['prune2_xz'], t['prune2_lossless_total'], t['prune1_xz']]
colors1 = [MUTED, HEADER, ICON, ACCENT, SEM_OK, ACCENT]
fig, ax = plt.subplots(figsize=(8.6, 4.2), constrained_layout=True)
bars = ax.barh(labels1, vals1, color=colors1, height=0.62, edgecolor='none')
for b, v in zip(bars, vals1):
    ax.text(v + 0.8, b.get_y() + b.get_height() / 2, f'{v:.1f}%',
            va='center', fontsize=10, color=TEXTC, fontweight='bold')
ax.set_xlim(0, 72)
style_ax(ax)
ax.set_xticks([0, 10, 20, 30, 40, 50, 60, 70])
fig.savefig(os.path.join(OUT, 'chart_text.png'), dpi=200)
plt.close(fig)

# ── График 2: журнал операций, 200 тыс. шагов ──
j = RES['journal']
labels2 = [
    'Снежный ком (шаг выводится\nиз состояния) + xz',
    'Токен-запись (op+шаг) + xz',
    'UHC-бинарный varint + xz',
    'Текстовый журнал + xz',
]
vals2 = [j['snow_raw_xz'], j['token_binary_xz'], j['uhc_binary_xz'], j['raw_xz']]
colors2 = [SEM_OK, ACCENT, ICON, HEADER]
fig, ax = plt.subplots(figsize=(8.6, 3.6), constrained_layout=True)
bars = ax.barh(labels2, vals2, color=colors2, height=0.58, edgecolor='none')
for b, v in zip(bars, vals2):
    ax.text(v + 0.5, b.get_y() + b.get_height() / 2, f'{v:.2f}%',
            va='center', fontsize=10, color=TEXTC, fontweight='bold')
ax.set_xlim(0, 40)
style_ax(ax)
ax.set_xticks([0, 10, 20, 30, 40])
fig.savefig(os.path.join(OUT, 'chart_journal.png'), dpi=200)
plt.close(fig)

# ── График 3: сегменты 10 МБ — базовый xz против лучшей обратимой схемы ──
seg_order = ['text', 'skewed_o0', 'markov_o1', 'smooth_signal', 'records', 'sparse', 'repeats', 'random']
best_name_map = {'smooth_signal': 'delta-1 + zstd', 'records': 'транспонирование + zstd'}
rows = []
for name in seg_order:
    r = next(x for x in RES['binary']['segments'] if x['name'] == name)
    base = r['xz']
    cands = {k: v for k, v in r.items() if k.endswith('_zstd') and v is not None}
    cands['zstd19'] = r['zstd19']
    best_k = min(cands, key=cands.get)
    best = cands[best_k]
    label = {'delta1_zstd': 'delta-1', 'xorprev_zstd': 'xor-prev', 'planesplit_zstd': 'транспонирование',
             'xorstride16_zstd': 'xor-шаг16', 'zstd19': 'zstd-19'}[best_k]
    rows.append((name, base, best, label))
short = {'text': 'Текст (Zipf)', 'skewed_o0': 'Скошенный байтовый', 'markov_o1': 'Марковская цепь',
         'smooth_signal': 'Гладкий сигнал', 'records': 'Структурированные записи',
         'sparse': 'Разреженный', 'repeats': 'Повторяющийся', 'random': 'Случайный'}
ylabels = [f'{short[n]}\n({lbl})' for n, b, bt, lbl in rows]
base_vals = [b for n, b, bt, l in rows]
best_vals = [bt for n, b, bt, l in rows]
import numpy as np
y = np.arange(len(rows))
fig, ax = plt.subplots(figsize=(9.2, 5.2), constrained_layout=True)
ax.barh(y - 0.19, base_vals, height=0.34, color=HEADER, label='xz (базовый)')
ax.barh(y + 0.19, best_vals, height=0.34, color=ACCENT, label='лучшая обратимая схема')
for i, (bv, bt) in enumerate(zip(base_vals, best_vals)):
    ax.text(bv + 1.2, i - 0.19, f'{bv:.1f}', va='center', fontsize=9, color=MUTED)
    ax.text(bt + 1.2, i + 0.19, f'{bt:.1f}', va='center', fontsize=9, color=TEXTC, fontweight='bold')
ax.set_yticks(y); ax.set_yticklabels(ylabels, fontsize=9.5)
ax.invert_yaxis()
ax.set_xlim(0, 112)
style_ax(ax)
ax.legend(loc='upper right', frameon=False, fontsize=10, bbox_to_anchor=(1.0, 1.02))
fig.savefig(os.path.join(OUT, 'chart_binary.png'), dpi=200)
plt.close(fig)

for f in ('chart_text.png', 'chart_journal.png', 'chart_binary.png'):
    p = os.path.join(OUT, f)
    from PIL import Image
    im = Image.open(p).convert('L')
    h = im.histogram()
    print(f, im.size, 'non-white ratio:', round(1 - h[255] / sum(h), 4))
