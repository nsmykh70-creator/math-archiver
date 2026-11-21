//! Стенографические аккорды: кодирование текста нажатиями пронумерованной
//! клавиатуры (1..=24) с полной, без потерь обратимостью.
//!
//! # Модель
//!
//! Аккорд — одновременное нажатие подмножества клавиш; внутри он хранится
//! битовой маской `u32` (бит `k-1` = клавиша `k`). Словарь сопоставляет
//! частые токены (слова, знаки, пробелы) аккордам; редкое уходит в fallback —
//! посимвольное UTF-8 кодирование ниббл-аккордами.
//!
//! # Нормализация гомоглифов
//!
//! Двенадцать пар букв, визуально совпадающих в кириллице и латинице
//! (`А/A`, `В/B`, `Е/E`, `К/K`, `М/M`, `Н/H`, `О/O`, `Р/P`, `С/C`, `Т/T`,
//! `У/Y`, `Х/X`), сводятся к одному каноническому символу — поэтому один
//! аккорд обозначает ОБЕ буквы (например, `с` и `c` — один аккорд).
//! Исходный алфавит и регистр восстанавливаются служебными маркерами
//! (аккордами): алфавит — «защёлка», маркер пишется только при смене
//! (старт потока — кириллица); регистр — маркеры «Заглавный»/«ВЕРХНИЙ»
//! перед словом, нижний — по умолчанию без маркера. Слова, не попадающие
//! в канонические схемы (смешанный регистр `FooBar`, смешанный алфавит
//! `kо`), кодируются fallback-ом дословно — обратимость 100% для любого
//! Unicode-текста.
//!
//! # Плотная упаковка (`pack_bytes`)
//!
//! `[u32 BE: число аккордов] + битовый поток (MSB-first, без выравнивания)`:
//! - одиночная клавиша — 5 бит (номер клавиши − 1);
//! - прочий аккорд — 5 бит кода `24` + 24 бита полной маски.
//!
//! Частотный словарь назначает частым токенам аккорды из двух клавиш
//! (15 бит), маркерам — одиночные клавиши (5 бит), поэтому словарное слово
//! в нижнем регистре стоит 15 бит, с Заглавной/ВЕРХНИМ — 20, а не 12–30
//! байт исходного UTF-8.
//!
//! # Fallback
//!
//! `raw_byte` (клавиши 1+3) и `raw_run` (клавиши 1+2) — служебные аккорды:
//! за ними идут нибблы (клавиши 9..24, по 5 бит) и UTF-8 байты, поэтому
//! любой неизвестный символ (цифры, эмодзи, CJK) тоже обратим.

use std::collections::{HashMap, HashSet};
use std::fmt;

// ---------------------------------------------------------------------------
// Ошибки
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum StenoError {
    InvalidKey(u8),
    EmptyChord,
    InvalidMask(u32),
    UnexpectedEndOfStream,
    TrailingBitsNotZero,
    InvalidNibbleChord(u32),
    InvalidUtf8Fallback,
    UnknownChord(u32),
    InvalidChordPair(u32, u32),
    RawRunTooLong(usize),
    DictionaryConflict(u32),
}

impl fmt::Display for StenoError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            StenoError::InvalidKey(k) => write!(f, "клавиша {k} вне диапазона 1..=24"),
            StenoError::EmptyChord => write!(f, "пустой аккорд (ни одной клавиши)"),
            StenoError::InvalidMask(m) => write!(f, "маска {m:#08x} выходит за 24 бита"),
            StenoError::UnexpectedEndOfStream => write!(f, "неожиданный конец потока аккордов"),
            StenoError::TrailingBitsNotZero => write!(f, "хвостовые биты упаковки не нулевые"),
            StenoError::InvalidNibbleChord(m) => {
                write!(f, "аккорд {m:#08x} не является нибблом (клавиши 9..24)")
            }
            StenoError::InvalidUtf8Fallback => {
                write!(f, "fallback-нагрузка не является корректным UTF-8")
            }
            StenoError::UnknownChord(m) => write!(f, "аккорд {m:#08x} не известен в этом контексте"),
            StenoError::InvalidChordPair(a, b) => {
                write!(f, "пара клавиш {a}/{b} некорректна (нужны 1..=24 по возрастанию)")
            }
            StenoError::RawRunTooLong(n) => write!(f, "fallback-последовательность слишком длинная: {n}"),
            StenoError::DictionaryConflict(m) => write!(f, "конфликт аккорда в словаре: {m:#08x}"),
        }
    }
}

impl std::error::Error for StenoError {}

// ---------------------------------------------------------------------------
// Аккорд
// ---------------------------------------------------------------------------

pub const MAX_KEYS: u8 = 24;
pub const KEY_MASK_ALL: u32 = (1_u32 << MAX_KEYS) - 1;

/// Аккорд 24-клавишной клавиатуры: бит `k-1` маски — нажатая клавиша `k`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct Chord {
    mask: u32,
}

impl Chord {
    /// Аккорд из набора клавиш (1..=24); повторные клавиши схлопываются.
    pub fn from_keys(keys: &[u8]) -> Result<Self, StenoError> {
        let mut mask = 0_u32;
        for &k in keys {
            if !(1..=MAX_KEYS).contains(&k) {
                return Err(StenoError::InvalidKey(k));
            }
            mask |= 1_u32 << (k - 1);
        }
        Self::from_mask(mask)
    }

    /// Аккорд из маски; ноль запрещён, биты выше 24-го — ошибка.
    pub fn from_mask(mask: u32) -> Result<Self, StenoError> {
        if mask & !KEY_MASK_ALL != 0 {
            return Err(StenoError::InvalidMask(mask));
        }
        if mask == 0 {
            return Err(StenoError::EmptyChord);
        }
        Ok(Self { mask })
    }

    pub const fn mask(self) -> u32 {
        self.mask
    }

    /// Нажатые клавиши по возрастанию.
    pub fn keys(self) -> Vec<u8> {
        (0..MAX_KEYS)
            .filter(|&bit| self.mask & (1_u32 << bit) != 0)
            .map(|bit| bit + 1)
            .collect()
    }

    pub const fn is_single_key(self) -> bool {
        self.mask.is_power_of_two()
    }

    /// Клавиша одиночного аккорда (1..=24) или None для аккорда из 2+ клавиш.
    pub fn single_key(self) -> Option<u8> {
        if self.is_single_key() {
            Some(self.mask.trailing_zeros() as u8 + 1)
        } else {
            None
        }
    }

    pub const fn popcount(self) -> u32 {
        self.mask.count_ones()
    }

    /// Старшие 24 бита маски — 3 байта (big-endian).
    pub const fn to_3_bytes(self) -> [u8; 3] {
        [
            ((self.mask >> 16) & 0xFF) as u8,
            ((self.mask >> 8) & 0xFF) as u8,
            (self.mask & 0xFF) as u8,
        ]
    }

    pub fn from_3_bytes(b: [u8; 3]) -> Result<Self, StenoError> {
        Self::from_mask(((b[0] as u32) << 16) | ((b[1] as u32) << 8) | (b[2] as u32))
    }
}

impl fmt::Display for Chord {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let keys = self.keys();
        for (i, k) in keys.iter().enumerate() {
            if i > 0 {
                write!(f, "-")?;
            }
            write!(f, "{k}")?;
        }
        Ok(())
    }
}

// ---------------------------------------------------------------------------
// Плотная битовая упаковка
// ---------------------------------------------------------------------------

struct BitWriter {
    bytes: Vec<u8>,
    bit_pos: usize,
}

impl BitWriter {
    fn new() -> Self {
        Self { bytes: Vec::new(), bit_pos: 0 }
    }

    /// Записывает `n` младших битов `value`, старший бит первым.
    fn write_bits(&mut self, value: u32, n: u8) {
        for i in (0..n).rev() {
            if self.bit_pos % 8 == 0 {
                self.bytes.push(0);
            }
            if (value >> i) & 1 == 1 {
                let last = self.bytes.len() - 1;
                self.bytes[last] |= 1 << (7 - self.bit_pos % 8);
            }
            self.bit_pos += 1;
        }
    }

    fn finish(self) -> Vec<u8> {
        self.bytes
    }
}

struct BitReader<'a> {
    bytes: &'a [u8],
    bit_pos: usize,
    bit_len: usize,
}

impl<'a> BitReader<'a> {
    fn new(bytes: &'a [u8]) -> Self {
        Self { bytes, bit_pos: 0, bit_len: bytes.len() * 8 }
    }

    fn read_bits(&mut self, n: u8) -> Result<u32, StenoError> {
        if self.bit_pos + n as usize > self.bit_len {
            return Err(StenoError::UnexpectedEndOfStream);
        }
        let mut v = 0_u32;
        for _ in 0..n {
            let bit = (self.bytes[self.bit_pos / 8] >> (7 - self.bit_pos % 8)) & 1;
            v = (v << 1) | bit as u32;
            self.bit_pos += 1;
        }
        Ok(v)
    }

    /// Хвост упаковки обязан состоять из нулевых битов выравнивания (< 8 шт).
    fn expect_padded_zero(&self) -> Result<(), StenoError> {
        let rem = self.bit_len - self.bit_pos;
        if rem >= 8 {
            return Err(StenoError::TrailingBitsNotZero);
        }
        for p in self.bit_pos..self.bit_len {
            if (self.bytes[p / 8] >> (7 - p % 8)) & 1 != 0 {
                return Err(StenoError::TrailingBitsNotZero);
            }
        }
        Ok(())
    }
}

/// Плотная упаковка: `[u32 BE: число аккордов] + битовый поток`.
/// Одиночная клавиша — 5 бит; аккорд из двух клавиш — код 25 + 2×5 бит
/// (номера клавиш по возрастанию); прочий аккорд — код 24 + 24 бита маски.
/// Коды 26..31 зарезервированы. Хвостовые биты выравнивания — нули.
pub fn pack_bytes(chords: &[Chord]) -> Vec<u8> {
    let mut w = BitWriter::new();
    for c in chords {
        let m = c.mask();
        if c.is_single_key() {
            w.write_bits(m.trailing_zeros(), 5);
        } else if c.popcount() == 2 {
            w.write_bits(25, 5);
            let a = m.trailing_zeros() as u32 + 1;
            let b = (m & (m - 1)).trailing_zeros() + 1;
            w.write_bits(a, 5);
            w.write_bits(b, 5);
        } else {
            w.write_bits(24, 5);
            w.write_bits(m, 24);
        }
    }
    let mut out = Vec::with_capacity(4 + w.bytes.len());
    out.extend_from_slice(&(chords.len() as u32).to_be_bytes());
    out.extend_from_slice(&w.finish());
    out
}

/// Обратная к `pack_bytes`; проверяет, что хвостовые биты выравнивания нулевые.
pub fn unpack_bytes(bytes: &[u8]) -> Result<Vec<Chord>, StenoError> {
    if bytes.len() < 4 {
        return Err(StenoError::UnexpectedEndOfStream);
    }
    let count = u32::from_be_bytes([bytes[0], bytes[1], bytes[2], bytes[3]]) as usize;
    let mut r = BitReader::new(&bytes[4..]);
    let mut chords = Vec::with_capacity(count.min(4096));
    for _ in 0..count {
        let code = r.read_bits(5)?;
        let mask = match code {
            0..=23 => 1_u32 << code,
            24 => r.read_bits(24)?,
            25 => {
                let a = r.read_bits(5)?;
                let b = r.read_bits(5)?;
                if !(1..=24).contains(&a) || !(1..=24).contains(&b) || a >= b {
                    return Err(StenoError::InvalidChordPair(a, b));
                }
                (1_u32 << (a - 1)) | (1_u32 << (b - 1))
            }
            _ => return Err(StenoError::UnknownChord(code as u32)),
        };
        chords.push(Chord::from_mask(mask)?);
    }
    r.expect_padded_zero()?;
    Ok(chords)
}

// ---------------------------------------------------------------------------
// Нормализация: гомоглифы, алфавит, регистр
// ---------------------------------------------------------------------------

/// Алфавит символа.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Script {
    Cyrillic,
    Latin,
    Neutral,
}

/// Схема регистра слова.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CaseKind {
    Lower,
    Capitalized,
    Upper,
}

/// Двенадцать гомоглифных пар «кириллица — латиница» (строчные).
/// Канонический символ пары — кириллический.
pub const TWIN_PAIRS: [(char, char); 12] = [
    ('а', 'a'), ('в', 'b'), ('е', 'e'), ('к', 'k'), ('м', 'm'), ('н', 'h'),
    ('о', 'o'), ('р', 'p'), ('с', 'c'), ('т', 't'), ('у', 'y'), ('х', 'x'),
];

fn is_cyrillic(c: char) -> bool {
    ('\u{0400}'..='\u{04FF}').contains(&c) || ('\u{0500}'..='\u{052F}').contains(&c)
}

/// Латинский близнец канонической кириллической буквы.
fn lat_twin(canon: char) -> Option<char> {
    TWIN_PAIRS.iter().find(|&&(c, _)| c == canon).map(|&(_, l)| l)
}

/// Канонический (кириллический) близнец латинской буквы.
fn cyr_twin(lat_lower: char) -> Option<char> {
    TWIN_PAIRS.iter().find(|&&(_, l)| l == lat_lower).map(|&(c, _)| c)
}

/// Символ -> (канонический строчный символ, алфавит).
/// Пары гомоглифов сводятся к кириллическому канону; алфавит источника
/// сохраняется отдельно и в аккорде не теряется.
pub fn normalize_char(ch: char) -> (char, Script) {
    let lower = ch.to_lowercase().next().unwrap_or(ch);
    if is_cyrillic(lower) {
        (lower, Script::Cyrillic)
    } else if lower.is_ascii_alphabetic() {
        // 'a' -> ('а', Latin): канон кириллический, алфавит запомнен
        (cyr_twin(lower).unwrap_or(lower), Script::Latin)
    } else if lower.is_alphabetic() {
        (lower, Script::Neutral) // греческие, CJK и прочие письменности
    } else {
        (lower, Script::Neutral) // цифры, знаки
    }
}

/// Канонический символ -> исходный символ для данного алфавита.
/// `None` значит «такое сочетание канона и алфавита невозможно» (поток битый).
pub fn denormalize_char(canon: char, script: Script) -> Option<char> {
    match script {
        Script::Cyrillic => {
            if lat_twin(canon).is_some() || is_cyrillic(canon) {
                Some(canon)
            } else {
                None
            }
        }
        Script::Latin => {
            if let Some(lat) = lat_twin(canon) {
                Some(lat)
            } else if !is_cyrillic(canon) {
                Some(canon) // 's', 'l' и прочие без кириллического близнеца
            } else {
                None
            }
        }
        Script::Neutral => {
            if lat_twin(canon).is_none() && !is_cyrillic(canon) {
                Some(canon)
            } else {
                None
            }
        }
    }
}

fn detect_case(chars: &[char]) -> Option<CaseKind> {
    let alpha: Vec<char> = chars.iter().copied().filter(|c| c.is_alphabetic()).collect();
    if alpha.is_empty() {
        return Some(CaseKind::Lower); // цифры: регистра нет; слово всё равно уйдёт в fallback
    }
    let upper = alpha.iter().filter(|c| c.is_uppercase()).count();
    if upper == 0 {
        return Some(CaseKind::Lower);
    }
    if upper == alpha.len() {
        return Some(CaseKind::Upper);
    }
    if upper == 1 && alpha[0].is_uppercase() {
        return Some(CaseKind::Capitalized);
    }
    None // FooBar, iPhone, oO — смешанный регистр: только дословный fallback
}

struct CanonWord {
    canon: String,
    script: Script,
    case: CaseKind,
}

/// Канонизация слова: единый канон гомоглифов + схема регистра + алфавит.
/// `None` — слово не подходит под канонические схемы (уходит в fallback).
fn canonicalize_word(word: &str) -> Option<CanonWord> {
    let chars: Vec<char> = word.chars().collect();
    let case = detect_case(&chars)?;
    let mut canon = String::with_capacity(chars.len());
    let mut script: Option<Script> = None;
    for &ch in &chars {
        let (c, s) = normalize_char(ch);
        canon.push(c);
        if ch.is_alphabetic() {
            match script {
                None => script = Some(s),
                Some(prev) if prev != s => return None, // смешанный алфавит: kо, oO
                _ => {}
            }
        }
    }
    match script? {
        Script::Cyrillic | Script::Latin => {}
        Script::Neutral => return None,
    }
    Some(CanonWord { canon, script: script.unwrap(), case })
}

fn apply_case(word: &str, case: CaseKind) -> String {
    match case {
        CaseKind::Lower => word.to_string(),
        CaseKind::Upper => word.chars().flat_map(|c| c.to_uppercase()).collect(),
        CaseKind::Capitalized => {
            let mut chars = word.chars();
            match chars.next() {
                None => String::new(),
                Some(first) => first.to_uppercase().collect::<String>() + chars.as_str(),
            }
        }
    }
}

// ---------------------------------------------------------------------------
// Словарь
// ---------------------------------------------------------------------------

/// Служебная пунктуация (пробел — клавиша 1, точка — 7, запятая — 8).
const PUNCT_TOKENS: [char; 17] = [
    '\n', '\t', '!', '?', ':', ';', '-', '—', '«', '»', '(', ')', '"',
    '\'', '…', '/', '№',
];

/// Частотные слова: русские служебные и топ-существительные, английские
/// служебные и технические. Ключи словаря — канонические (гомоглифы сведены):
/// `the` хранится как `тне`, `но` и `no` — один ключ.
const WORD_TOKENS: &[&str] = &[
    // --- русские служебные слова ---
    "и", "в", "не", "на", "я", "быть", "что", "он", "с", "как", "а", "то",
    "все", "она", "так", "его", "но", "да", "ты", "к", "у", "же", "вы", "за",
    "бы", "по", "только", "её", "мне", "было", "вот", "от", "меня", "ещё",
    "нет", "о", "из", "ему", "теперь", "когда", "даже", "ну", "вдруг", "ли",
    "если", "уже", "или", "ни", "был", "него", "до", "вас", "нибудь", "опять",
    "уж", "вам", "ведь", "там", "потом", "себя", "ничего", "ей", "может",
    "они", "тут", "где", "есть", "надо", "ней", "для", "мы", "тебя", "их",
    "чем", "была", "сам", "чтоб", "без", "будто", "чего", "раз", "тоже",
    "себе", "под", "будет", "тогда", "кто", "этот", "того", "потому",
    "этого", "какой", "совсем", "ним", "здесь", "этом", "один", "почти",
    "мой", "тем", "чтобы", "нее", "кажется", "сейчас", "были", "куда",
    "зачем", "всех", "никогда", "можно", "при", "наконец", "два", "об",
    "другой", "хоть", "после", "над", "больше", "тот", "через", "эти",
    "нас", "про", "всего", "них", "какая", "много", "разве", "три", "эту",
    "моя", "впрочем", "хорошо", "свою", "этой", "перед", "иногда", "лучше",
    "чуть", "том", "нельзя", "такой", "им", "более", "всегда", "конечно",
    "всю", "между",
    // --- русские частые существительные и тематика проекта ---
    "год", "человек", "время", "дело", "жизнь", "день", "рука", "слово",
    "место", "лицо", "вопрос", "сторона", "конец", "голова", "дом",
    "работа", "пример", "число", "уровень", "результат", "данные",
    "система", "программа", "код", "тест", "текст", "строка", "файл",
    "проект", "модуль", "язык", "клавиша", "аккорд", "аккорды", "словарь",
    "ключ", "клавиатура", "стенография", "стенографии", "функция",
    "структура", "массив", "байт", "поток", "символ", "буква", "алфавит",
    "регистр", "проверка", "восстановление", "сжатие", "привет", "мир",
    "спасибо", "пожалуйста", "здравствуйте", "пока", "восстановится",
    // --- английские служебные слова (ключи получатся гомоглифными) ---
    "the", "be", "to", "of", "and", "in", "that", "have", "it", "for",
    "not", "on", "with", "he", "as", "you", "do", "at", "this", "but",
    "his", "by", "from", "they", "we", "say", "her", "she", "or", "an",
    "will", "my", "one", "all", "would", "there", "their", "what", "so",
    "up", "out", "if", "about", "who", "get", "which", "go", "me", "when",
    "make", "can", "like", "time", "no", "just", "him", "know", "take",
    "people", "into", "is", "was", "are", "been", "has", "were",
    // --- английская тематика ---
    "hello", "world", "rust", "code", "test", "data", "text", "chord",
    "keyboard", "steno", "dictionary", "steganography",
    // --- русские словоформы (частые падежи и множественное число) ---
    "это", "эта", "этих", "слов", "слова", "слове", "словам", "байта",
    "байте", "байтов", "данных", "системы", "системе", "систему",
    "программы", "программе", "файла", "файлы", "кода", "коде", "теста",
    "тестов", "текста", "тексте", "строке", "строки", "строк", "языке",
    "языка", "клавиатуры", "клавиатуре", "аккордов", "аккорде", "аккорда",
    "восстановления", "проверки", "проверку", "года", "году", "годы",
    "лет", "человека", "времени", "дела", "жизни", "дня", "дни", "руки",
    "месте", "места", "вопроса", "вопросы", "стороны", "конце", "дома",
    "работе", "работы", "примеры", "числе", "уровня", "результата",
    "маркер", "маркера", "маркеры", "маркером", "маркерами",
    "превращаются", "занимают", "восстанавливается", "восстанавливаются",
    "посимвольный", "частые", "редкие", "букв", "символов", "клавиш",
    "клавиши", "нажатие", "нажатий", "бита", "битов", "потоков",
    "функции", "структуры", "массивы", "пунктуация", "регистре",
    "алфавита", "алфавите", "регистров", "аккордами", "аккордах",
    // --- английские словоформы ---
    "chords", "words", "letters", "bytes", "keys", "tests", "texts",
    "files", "lines", "system", "systems", "codes", "punctuation",
    "keyboards", "encoding", "decoding", "encode", "decode", "compression",
];

/// Раскладка одиночных клавиш 1..8: самые частые знаки и все маркеры.
/// Клавиши 9..24 зарезервированы под нибблы fallback-а.
const KEY_SPACE: u8 = 1;
const KEY_CASE_LOWER: u8 = 2;
const KEY_CASE_CAP: u8 = 3;
const KEY_CASE_UPPER: u8 = 4;
const KEY_SCRIPT_CYR: u8 = 5;
const KEY_SCRIPT_LAT: u8 = 6;
const KEY_PERIOD: u8 = 7;
const KEY_COMMA: u8 = 8;
/// Служебные аккорды fallback-а: две клавиши одновременно.
const KEYS_RAW_RUN: [u8; 2] = [1, 2];
const KEYS_RAW_BYTE: [u8; 2] = [1, 3];
/// Ниббл n (0..15) — одиночный аккорд клавиши 9+n.
const NIBBLE_KEY_BASE: u8 = 9;

/// Выдает свободные маски для словаря. Фаза 0 — все двухклавишные аккорды
/// (упаковка 15 бит), фаза 1 — более широкие (29 бит). Одиночные клавиши
/// заняты маркерами и нибблами, служебные аккорды 1+2 и 1+3 — fallback-ом.
struct MaskAllocator {
    phase: u8,
    candidate: u32,
    used: HashSet<u32>,
}

impl MaskAllocator {
    fn new(reserved: HashSet<u32>) -> Self {
        Self { phase: 0, candidate: 6, used: reserved }
    }

    fn scan(&mut self) -> Option<u32> {
        while self.candidate <= KEY_MASK_ALL {
            let m = self.candidate;
            self.candidate += 1;
            if m == 3 || m == 5 {
                continue; // raw_run и raw_byte
            }
            let pc = m.count_ones();
            let accept = if self.phase == 0 { pc == 2 } else { pc >= 3 };
            if !accept || self.used.contains(&m) {
                continue;
            }
            self.used.insert(m);
            return Some(m);
        }
        None
    }

    fn next(&mut self) -> Option<u32> {
        if let Some(m) = self.scan() {
            return Some(m);
        }
        if self.phase == 0 {
            self.phase = 1;
            self.candidate = 6;
            return self.scan();
        }
        None
    }
}

/// Словарь «токен <-> аккорд» плюс служебные аккорды. Двунаправленный:
/// кодирование и декодирование используют согласованные таблицы.
pub struct StenoDictionary {
    word_to_chord: HashMap<String, Chord>,
    chord_to_word: HashMap<u32, String>,
    punct_to_chord: HashMap<char, Chord>,
    chord_to_punct: HashMap<u32, char>,
    order: Vec<String>,
    space: Chord,
    comma: Chord,
    case_lower: Chord,
    case_cap: Chord,
    case_upper: Chord,
    script_cyr: Chord,
    script_lat: Chord,
    script_neu: Chord,
    raw_run: Chord,
    raw_byte: Chord,
}

impl StenoDictionary {
    /// Строит словарь по умолчанию: маркеры на одиночных клавишах 1..8,
    /// fallback-аккорды 1+2 и 1+3, пунктуация и частотные слова — на
    /// двухклавишных аккордах (по возрастанию маски).
    pub fn build_default() -> Result<Self, StenoError> {
        let space = Chord::from_keys(&[KEY_SPACE])?;
        let case_lower = Chord::from_keys(&[KEY_CASE_LOWER])?;
        let case_cap = Chord::from_keys(&[KEY_CASE_CAP])?;
        let case_upper = Chord::from_keys(&[KEY_CASE_UPPER])?;
        let script_cyr = Chord::from_keys(&[KEY_SCRIPT_CYR])?;
        let script_lat = Chord::from_keys(&[KEY_SCRIPT_LAT])?;
        let period = Chord::from_keys(&[KEY_PERIOD])?;
        let comma = Chord::from_keys(&[KEY_COMMA])?;
        let raw_run = Chord::from_keys(&KEYS_RAW_RUN)?;
        let raw_byte = Chord::from_keys(&KEYS_RAW_BYTE)?;

        let mut used: HashSet<u32> = HashSet::new();
        for c in [space, case_lower, case_cap, case_upper, script_cyr,
                  script_lat, period, comma, raw_run, raw_byte] {
            if !used.insert(c.mask()) {
                return Err(StenoError::DictionaryConflict(c.mask()));
            }
        }

        let mut d = Self {
            word_to_chord: HashMap::new(),
            chord_to_word: HashMap::new(),
            punct_to_chord: HashMap::new(),
            chord_to_punct: HashMap::new(),
            order: Vec::new(),
            space,
            comma,
            case_lower,
            case_cap,
            case_upper,
            script_cyr,
            script_lat,
            script_neu: space, // замещается ниже первым свободным аккордом
            raw_run,
            raw_byte,
        };
        for (ch, c) in [(' ', space), ('.', period), (',', comma)] {
            d.punct_to_chord.insert(ch, c);
            d.chord_to_punct.insert(c.mask(), ch);
        }

        let mut alloc = MaskAllocator::new(used);
        // маркер «прочее» — первый свободный парный аккорд (кодировщиком
        // не используется: такие слова всегда идут в fallback)
        d.script_neu = Chord::from_mask(alloc.next().ok_or(StenoError::DictionaryConflict(0))?)?;
        for ch in PUNCT_TOKENS {
            let mask = alloc.next().ok_or(StenoError::DictionaryConflict(0))?;
            let chord = Chord::from_mask(mask)?;
            d.punct_to_chord.insert(ch, chord);
            d.chord_to_punct.insert(mask, ch);
        }

        let mut seen: HashSet<String> = HashSet::new();
        for token in WORD_TOKENS {
            let Some(info) = canonicalize_word(token) else { continue };
            if !seen.insert(info.canon.clone()) || d.word_to_chord.contains_key(&info.canon) {
                continue; // «to» и «то» — один ключ: аккорд общий, алфавит в маркере
            }
            let mask = alloc.next().ok_or(StenoError::DictionaryConflict(0))?;
            let chord = Chord::from_mask(mask)?;
            d.word_to_chord.insert(info.canon.clone(), chord);
            d.chord_to_word.insert(mask, info.canon);
            d.order.push((*token).to_string());
        }
        Ok(d)
    }

    pub fn word_count(&self) -> usize {
        self.word_to_chord.len()
    }

    pub fn punct_count(&self) -> usize {
        self.punct_to_chord.len()
    }

    /// Слова в порядке добавления: (исходный токен, аккорд).
    pub fn words(&self) -> Vec<(&str, Chord)> {
        self.order
            .iter()
            .map(|t| {
                let info = canonicalize_word(t).expect("токен словаря каноничен");
                (t.as_str(), self.word_to_chord[&info.canon])
            })
            .collect()
    }

    pub fn space_chord(&self) -> Chord {
        self.space
    }

    pub fn comma_chord(&self) -> Chord {
        self.comma
    }

    pub fn raw_run_chord(&self) -> Chord {
        self.raw_run
    }

    pub fn raw_byte_chord(&self) -> Chord {
        self.raw_byte
    }

    pub fn script_neu_chord(&self) -> Chord {
        self.script_neu
    }

    pub fn nibble_chord(n: u32) -> Result<Chord, StenoError> {
        Chord::from_mask(1_u32 << (NIBBLE_KEY_BASE as u32 - 1 + n))
    }

    fn nibble_value(c: Chord) -> Result<u32, StenoError> {
        let m = c.mask();
        if m.count_ones() == 1 && (1_u32 << (NIBBLE_KEY_BASE - 1)) <= m
            && m <= (1_u32 << (MAX_KEYS - 1))
        {
            Ok(m.trailing_zeros() - (NIBBLE_KEY_BASE as u32 - 1))
        } else {
            Err(StenoError::InvalidNibbleChord(m))
        }
    }

    pub fn case_marker(&self, case: CaseKind) -> Chord {
        match case {
            CaseKind::Lower => self.case_lower,
            CaseKind::Capitalized => self.case_cap,
            CaseKind::Upper => self.case_upper,
        }
    }

    pub fn script_marker(&self, script: Script) -> Chord {
        match script {
            Script::Cyrillic => self.script_cyr,
            Script::Latin => self.script_lat,
            Script::Neutral => self.script_neu,
        }
    }

    fn push_nibbles(bytes: &[u8], out: &mut Vec<Chord>) -> Result<(), StenoError> {
        for &b in bytes {
            out.push(Self::nibble_chord((b >> 4) as u32)?);
            out.push(Self::nibble_chord((b & 0xF) as u32)?);
        }
        Ok(())
    }

    fn flush_raw(&self, bytes: &[u8], out: &mut Vec<Chord>) -> Result<(), StenoError> {
        if bytes.is_empty() {
            return Ok(());
        }
        if bytes.len() == 1 {
            out.push(self.raw_byte);
            return Self::push_nibbles(bytes, out);
        }
        let len = bytes.len();
        if len > (KEY_MASK_ALL as usize) {
            return Err(StenoError::RawRunTooLong(len));
        }
        out.push(self.raw_run);
        out.push(Chord::from_mask(len as u32)?);
        Self::push_nibbles(bytes, out)
    }

    fn flush_word(
        &self,
        word: &str,
        pending: &mut Vec<u8>,
        out: &mut Vec<Chord>,
        latch: &mut Script,
    ) -> Result<(), StenoError> {
        if word.is_empty() {
            return Ok(());
        }
        let found = canonicalize_word(word)
            .and_then(|info| self.word_to_chord.get(&info.canon).map(|&c| (info, c)));
        if let Some((info, chord)) = found {
            self.flush_raw(pending, out)?;
            pending.clear();
            if info.script != *latch {
                // защёлка алфавита: пишется только при смене
                out.push(self.script_marker(info.script));
                *latch = info.script;
            }
            if info.case != CaseKind::Lower {
                // нижний регистр — по умолчанию, маркер не нужен
                out.push(self.case_marker(info.case));
            }
            out.push(chord);
        } else {
            // неизвестное или неканоничное слово — дословно в fallback
            pending.extend_from_slice(word.as_bytes());
        }
        Ok(())
    }

    /// Кодирует текст в последовательность аккордов; обратим на 100%.
    pub fn encode_to_chords(&self, text: &str) -> Result<Vec<Chord>, StenoError> {
        let mut out = Vec::new();
        let mut pending: Vec<u8> = Vec::new();
        let mut word = String::new();
        let mut latch = Script::Cyrillic;

        for ch in text.chars() {
            if ch.is_alphanumeric() {
                word.push(ch);
            } else {
                self.flush_word(&word, &mut pending, &mut out, &mut latch)?;
                word.clear();
                if let Some(&c) = self.punct_to_chord.get(&ch) {
                    self.flush_raw(&pending, &mut out)?;
                    pending.clear();
                    out.push(c);
                } else {
                    let mut buf = [0_u8; 4];
                    pending.extend_from_slice(ch.encode_utf8(&mut buf).as_bytes());
                }
            }
        }
        self.flush_word(&word, &mut pending, &mut out, &mut latch)?;
        self.flush_raw(&pending, &mut out)?;
        Ok(out)
    }

    fn read_raw_run(&self, chords: &[Chord], i: &mut usize) -> Result<Vec<u8>, StenoError> {
        if *i >= chords.len() {
            return Err(StenoError::UnexpectedEndOfStream);
        }
        let len = chords[*i].mask() as usize;
        *i += 1;
        if *i + 2 * len > chords.len() {
            return Err(StenoError::UnexpectedEndOfStream);
        }
        let mut bytes = Vec::with_capacity(len);
        for _ in 0..len {
            let hi = Self::nibble_value(chords[*i])?;
            let lo = Self::nibble_value(chords[*i + 1])?;
            *i += 2;
            bytes.push(((hi << 4) | lo) as u8);
        }
        Ok(bytes)
    }

    /// Декодирует аккорды обратно в исходный текст; любой конфликт — ошибка.
    /// Семантика зеркальна кодировщику: защёлка алфавита живёт до смены,
    /// маркер регистра относится к следующему слову, нижний — по умолчанию.
    pub fn decode_from_chords(&self, chords: &[Chord]) -> Result<String, StenoError> {
        let mut out = String::new();
        let mut i = 0_usize;
        let mut latch = Script::Cyrillic;
        while i < chords.len() {
            let c = chords[i];
            if c == self.raw_run {
                i += 1;
                let bytes = self.read_raw_run(chords, &mut i)?;
                let s = String::from_utf8(bytes).map_err(|_| StenoError::InvalidUtf8Fallback)?;
                out.push_str(&s);
                continue;
            }
            if c == self.raw_byte {
                i += 1;
                if i + 1 >= chords.len() {
                    return Err(StenoError::UnexpectedEndOfStream);
                }
                let hi = Self::nibble_value(chords[i])?;
                let lo = Self::nibble_value(chords[i + 1])?;
                i += 2;
                let s = String::from_utf8(vec![((hi << 4) | lo) as u8])
                    .map_err(|_| StenoError::InvalidUtf8Fallback)?;
                out.push_str(&s);
                continue;
            }
            if c == self.script_cyr || c == self.script_lat || c == self.script_neu {
                // защёлка алфавита — сама по себе ничего не выводит
                latch = if c == self.script_cyr {
                    Script::Cyrillic
                } else if c == self.script_lat {
                    Script::Latin
                } else {
                    Script::Neutral
                };
                i += 1;
                continue;
            }
            let case = if c == self.case_lower {
                CaseKind::Lower
            } else if c == self.case_cap {
                CaseKind::Capitalized
            } else if c == self.case_upper {
                CaseKind::Upper
            } else {
                // знак из словаря ИЛИ слово в нижнем регистре (по умолчанию,
                // без маркера — защёлка алфавита уже включена)
                if let Some(ch) = self.chord_to_punct.get(&c.mask()) {
                    out.push(*ch);
                    i += 1;
                    continue;
                }
                let canon = self.chord_to_word.get(&c.mask())
                    .ok_or(StenoError::UnknownChord(c.mask()))?;
                let mut word = String::with_capacity(canon.len());
                for ch in canon.chars() {
                    word.push(denormalize_char(ch, latch)
                        .ok_or(StenoError::UnknownChord(c.mask()))?);
                }
                out.push_str(&apply_case(&word, CaseKind::Lower));
                i += 1;
                continue;
            };
            // после маркера регистра обязан идти аккорд слова
            i += 1;
            if i >= chords.len() {
                return Err(StenoError::UnexpectedEndOfStream);
            }
            let canon = self.chord_to_word.get(&chords[i].mask())
                .ok_or(StenoError::UnknownChord(chords[i].mask()))?;
            let mut word = String::with_capacity(canon.len());
            for ch in canon.chars() {
                word.push(denormalize_char(ch, latch)
                    .ok_or(StenoError::UnknownChord(chords[i].mask()))?);
            }
            out.push_str(&apply_case(&word, case));
            i += 1;
        }
        Ok(out)
    }
}

// ---------------------------------------------------------------------------
// Тесты
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    fn roundtrip(dict: &StenoDictionary, text: &str) {
        let chords = dict.encode_to_chords(text).expect("encode");
        let packed = pack_bytes(&chords);
        let unpacked = unpack_bytes(&packed).expect("unpack");
        let decoded = dict.decode_from_chords(&unpacked).expect("decode");
        assert_eq!(decoded, text, "roundtrip failed for {text:?}");
    }

    #[test]
    fn test_chord_api_and_3bytes() {
        let c = Chord::from_keys(&[1, 8, 24]).unwrap();
        assert_eq!(c.keys(), vec![1, 8, 24]);
        assert_eq!(c.mask(), (1 << 0) | (1 << 7) | (1 << 23));
        assert_eq!(c.popcount(), 3);
        let back = Chord::from_3_bytes(c.to_3_bytes()).unwrap();
        assert_eq!(back, c);
        assert_eq!(Chord::from_keys(&[0]), Err(StenoError::InvalidKey(0)));
        assert_eq!(Chord::from_keys(&[25]), Err(StenoError::InvalidKey(25)));
        assert_eq!(Chord::from_keys(&[]), Err(StenoError::EmptyChord));
        assert_eq!(Chord::from_mask(0), Err(StenoError::EmptyChord));
        assert_eq!(Chord::from_mask(1 << 24), Err(StenoError::InvalidMask(1 << 24)));
        assert_eq!(c.to_string(), "1-8-24");
        let single = Chord::from_keys(&[7]).unwrap();
        assert_eq!(single.single_key(), Some(7));
        assert_eq!(single.to_3_bytes(), [0, 0, 64]);
    }

    #[test]
    fn test_pack_unpack_roundtrip_and_errors() {
        let cs: Vec<Chord> = [1u8, 2, 9, 24]
            .iter()
            .map(|&k| Chord::from_keys(&[k]).unwrap())
            .chain([Chord::from_keys(&[1, 24]).unwrap(), Chord::from_keys(&[3, 5, 17]).unwrap()])
            .collect();
        let packed = pack_bytes(&cs);
        assert_eq!(unpack_bytes(&packed).unwrap(), cs);
        // 6 аккордов: 4 одиночных (4×5 бит) + пара (15 бит) + тройка (29 бит)
        // = 64 бита = 8 байт — пад-бита нет, хвост бит в бит
        assert_eq!(packed.len(), 4 + 8);
        assert_eq!(unpack_bytes(&[]), Err(StenoError::UnexpectedEndOfStream));
        assert_eq!(unpack_bytes(&packed[..packed.len() - 1]), Err(StenoError::UnexpectedEndOfStream));
        // 3 одиночных = 15 бит -> 2 байта, 1 бит выравнивания
        let three: Vec<Chord> = [1u8, 2, 9]
            .iter()
            .map(|&k| Chord::from_keys(&[k]).unwrap())
            .collect();
        let p3 = pack_bytes(&three);
        assert_eq!(p3.len(), 4 + 2);
        let mut tampered = p3.clone();
        // общий бит 15 (последний) — бит выравнивания: в MSB-first потоке
        // это младший бит второго байта потока
        *tampered.last_mut().unwrap() |= 0x01;
        assert_eq!(unpack_bytes(&tampered), Err(StenoError::TrailingBitsNotZero));
        let mut bad_code = pack_bytes(&cs);
        bad_code[4] ^= 0xF0; // первые 5 бит: код 30 вместо одиночной клавиши
        assert_eq!(unpack_bytes(&bad_code), Err(StenoError::UnknownChord(30)));
        // неканоничная пара (ключи по убыванию) — ошибка
        let mut bad_pair = Vec::new();
        let mut wbits = BitWriter::new();
        wbits.write_bits(25, 5);
        wbits.write_bits(5, 5);
        wbits.write_bits(2, 5);
        bad_pair.extend_from_slice(&1_u32.to_be_bytes());
        bad_pair.extend_from_slice(&wbits.finish());
        assert_eq!(
            unpack_bytes(&bad_pair),
            Err(StenoError::InvalidChordPair(5, 2))
        );
    }

    #[test]
    fn test_homoglyph_normalization() {
        assert_eq!(normalize_char('A'), ('а', Script::Latin));
        assert_eq!(normalize_char('а'), ('а', Script::Cyrillic));
        assert_eq!(normalize_char('Х'), ('х', Script::Cyrillic));
        assert_eq!(normalize_char('x'), ('х', Script::Latin));
        assert_eq!(normalize_char('У'), ('у', Script::Cyrillic));
        assert_eq!(normalize_char('y'), ('у', Script::Latin));
        assert_eq!(normalize_char('s'), ('s', Script::Latin));
        assert_eq!(normalize_char('Л'), ('л', Script::Cyrillic));
        assert_eq!(denormalize_char('а', Script::Latin), Some('a'));
        assert_eq!(denormalize_char('а', Script::Cyrillic), Some('а'));
        assert_eq!(denormalize_char('х', Script::Latin), Some('x'));
        assert_eq!(denormalize_char('н', Script::Latin), Some('h'));
        assert_eq!(denormalize_char('s', Script::Latin), Some('s'));
        assert_eq!(denormalize_char('s', Script::Cyrillic), None);
        assert_eq!(denormalize_char('л', Script::Latin), None);
        assert_eq!(denormalize_char('а', Script::Neutral), None);
    }

    #[test]
    fn test_dictionary_invariants() {
        let dict = StenoDictionary::build_default().unwrap();
        // маркеры на одиночных клавишах 1..8
        assert_eq!(dict.case_lower.single_key(), Some(2));
        assert_eq!(dict.script_cyr.single_key(), Some(5));
        assert_eq!(dict.space.single_key(), Some(1));
        assert_eq!(dict.comma.single_key(), Some(8));
        // fallback-аккорды — двухклавишные
        assert_eq!(dict.raw_run.keys(), vec![1, 2]);
        assert_eq!(dict.raw_byte.keys(), vec![1, 3]);
        // двунаправленность словаря
        for (token, chord) in dict.words() {
            assert_eq!(dict.chord_to_word[&chord.mask()], canonicalize_word(token).unwrap().canon);
            assert!(chord.popcount() >= 2, "слово обязано занимать аккорд из 2+ клавиш");
            assert!(chord.single_key().is_none(), "нибблы и маркеры не пересекаются со словами");
        }
        // маски слов и пунктуации не пересекаются
        let punct_masks: HashSet<u32> = dict.chord_to_punct.keys().copied().collect();
        let word_masks: HashSet<u32> = dict.chord_to_word.keys().copied().collect();
        assert!(punct_masks.is_disjoint(&word_masks));
        assert!(dict.word_count() > 200, "словарь частотный: {}", dict.word_count());
        assert_eq!(dict.punct_count(), 20);
    }

    #[test]
    fn test_roundtrip_basic() {
        let dict = StenoDictionary::build_default().unwrap();
        let samples = [
            "Привет, мир!",
            "Hello, world!",
            "Многострочный\nтекст\tс табами и переносами: !?; — «кавычки» (скобки)…",
            "ЗАГЛАВНЫЕ СЛОВА, Заглавные Начала и обычные слова.",
            "Числа 2026, 7 и 1234567890; символы @#$%^&* и №",
            "Юникод: 日本語 / Ω / 🚀 / Привет 🌍!",
            "Tab\tи newline\nвнутри.",
            "— Тире в начале абзаца — тоже токен.",
            "",
            " ",
            "a",
            "Ёё Ї ї ў",
        ];
        for s in samples {
            roundtrip(&dict, s);
        }
    }

    #[test]
    fn test_homoglyph_text_roundtrip() {
        let dict = StenoDictionary::build_default().unwrap();
        let samples = [
            "Аналоги: к и k, р и r, о и o, е и e, А и A, Р и P, О и O, Е и E.",
            "с и c, у и y, х и x, В и B, М и M, Н и H, Т и T",
            "Смешанный:kod, тext, Руст,rust, КОд и cOdE.",
            "Канон общий, а маркер разделяет: word и ворd.",
        ];
        for s in samples {
            roundtrip(&dict, s);
        }
    }

    #[test]
    fn test_homoglyphs_share_chord() {
        let dict = StenoDictionary::build_default().unwrap();
        // «то» и «to» — один аккорд слова; нижний регистр маркера не требует,
        // защёлка алфавита стартует с кириллицы
        let ru = dict.encode_to_chords("то").unwrap();
        let en = dict.encode_to_chords("to").unwrap();
        assert_eq!(ru.len(), 1);
        assert_eq!(en.len(), 2);
        assert_eq!(en[0], dict.script_lat, "смена алфавита — защёлка");
        assert_eq!(ru[0], en[1], "канон общий -> аккорд общий");
        // «не» и «he» — тоже общий аккорд (близнецы н/h и о/o; n — нет!)
        let ru = dict.encode_to_chords("не").unwrap();
        let en = dict.encode_to_chords("he").unwrap();
        assert_eq!(ru.len(), 1);
        assert_eq!(en.len(), 2);
        assert_eq!(en[0], dict.script_lat);
        assert_eq!(ru[0], en[1]);
        roundtrip(&dict, "то");
        roundtrip(&dict, "to");
        roundtrip(&dict, "не");
        roundtrip(&dict, "he");
        // «с» и «c» — общий аккорд с однобуквенными словами
        let ru = dict.encode_to_chords("с").unwrap();
        let en = dict.encode_to_chords("c").unwrap();
        assert_eq!(ru.len(), 1);
        assert_eq!(en.len(), 2);
        assert_eq!(ru[0], en[1]);
        roundtrip(&dict, "с");
        roundtrip(&dict, "c");
    }

    #[test]
    fn test_case_and_mixed_case_words() {
        let dict = StenoDictionary::build_default().unwrap();
        for s in ["привет", "Привет", "ПРИВЕТ", "и", "И", "мир", "Мир", "МИР"] {
            roundtrip(&dict, s);
        }
        // смешанный регистр уходит в дословный fallback и тоже обратим
        for s in ["FooBar", "iPhone", "McDonald", "оО", "oO", "AAAbbb", "RustRu"] {
            roundtrip(&dict, s);
        }
        let chords = dict.encode_to_chords("FooBar").unwrap();
        assert_eq!(chords[0], dict.raw_run, "смешанный регистр — fallback");
        // нижний регистр без маркера, Заглавный/ВЕРХНИЙ — один маркер
        assert_eq!(dict.encode_to_chords("привет").unwrap().len(), 1);
        assert_eq!(dict.encode_to_chords("Привет").unwrap().len(), 2);
        assert_eq!(dict.encode_to_chords("ПРИВЕТ").unwrap().len(), 2);
    }

    #[test]
    fn test_mixed_script_word_falls_back() {
        let dict = StenoDictionary::build_default().unwrap();
        // «kо»: латинская k + кириллическая о — один канон, два алфавита
        for s in ["kо", "оОx", "Рython", "sлово"] {
            roundtrip(&dict, s);
        }
        let chords = dict.encode_to_chords("kо").unwrap();
        assert_eq!(chords[0], dict.raw_run);
    }

    #[test]
    fn test_raw_fallback_stream_shape() {
        let dict = StenoDictionary::build_default().unwrap();
        // 🚀 = 4 байта UTF-8: [raw_run][len=4][8 нибблов]
        let chords = dict.encode_to_chords("🚀").unwrap();
        assert_eq!(chords[0], dict.raw_run);
        assert_eq!(chords[1].mask(), 4);
        assert_eq!(chords.len(), 2 + 8);
        let decoded = dict.decode_from_chords(&chords).unwrap();
        assert_eq!(decoded, "🚀");
        // один байт идёт через raw_byte
        let chords = dict.encode_to_chords("z").unwrap();
        assert_eq!(chords[0], dict.raw_byte);
        assert_eq!(chords.len(), 3);
        assert_eq!(dict.decode_from_chords(&chords).unwrap(), "z");
    }

    #[test]
    fn test_nibble_chords_are_keys_9_to_24() {
        for n in 0..16_u32 {
            let c = StenoDictionary::nibble_chord(n).unwrap();
            assert_eq!(c.single_key(), Some(9 + n as u8));
        }
        assert!(StenoDictionary::nibble_chord(16).is_err());
    }

    #[test]
    fn test_decode_errors() {
        let dict = StenoDictionary::build_default().unwrap();
        let unknown = Chord::from_keys(&[1, 24]).unwrap();
        assert_eq!(dict.decode_from_chords(&[unknown]), Err(StenoError::UnknownChord(unknown.mask())));
        // маркер регистра без продолжения
        assert_eq!(dict.decode_from_chords(&[dict.case_lower]), Err(StenoError::UnexpectedEndOfStream));
        // после маркера регистра — не аккорд слова (защёлка алфавита словом не считается)
        assert_eq!(
            dict.decode_from_chords(&[dict.case_lower, dict.script_cyr]),
            Err(StenoError::UnknownChord(dict.script_cyr.mask()))
        );
        // после маркера регистра — знак из словаря
        assert_eq!(
            dict.decode_from_chords(&[dict.case_lower, dict.space]),
            Err(StenoError::UnknownChord(dict.space.mask()))
        );
        // после маркера регистра — аккорд не из словаря
        let unknown = Chord::from_keys(&[1, 24]).unwrap();
        assert_eq!(
            dict.decode_from_chords(&[dict.case_cap, unknown]),
            Err(StenoError::UnknownChord(unknown.mask()))
        );
        // raw_run с усечёнными нибблами
        assert_eq!(
            dict.decode_from_chords(&[dict.raw_run, Chord::from_mask(4).unwrap()]),
            Err(StenoError::UnexpectedEndOfStream)
        );
        // ниббл из запрещённой зоны (клавиша 5)
        assert_eq!(
            dict.decode_from_chords(&[dict.raw_byte, dict.script_cyr, dict.script_cyr]),
            Err(StenoError::InvalidNibbleChord(dict.script_cyr.mask()))
        );
        // сырые байты не образуют UTF-8 (0xF0 без продолжения)
        let mut bad = vec![dict.raw_run, Chord::from_mask(2).unwrap()];
        for b in [0xF0_u8, 0x9F] {
            bad.push(StenoDictionary::nibble_chord((b >> 4) as u32).unwrap());
            bad.push(StenoDictionary::nibble_chord((b & 0xF) as u32).unwrap());
        }
        assert_eq!(dict.decode_from_chords(&bad), Err(StenoError::InvalidUtf8Fallback));
    }

    #[test]
    fn test_script_neu_reserved() {
        let dict = StenoDictionary::build_default().unwrap();
        // маркер «прочее» существует, занимает парный аккорд, но кодировщиком
        // не используется: слова с нейтральным алфавитом идут в fallback
        assert_eq!(dict.script_neu.popcount(), 2);
        assert!(dict.script_neu.single_key().is_none());
        let chords = dict.encode_to_chords("привет мир the код").unwrap();
        assert!(!chords.contains(&dict.script_neu));
        let mut i = 0;
        let mut latch = Script::Cyrillic;
        while i < chords.len() {
            let c = chords[i];
            if c == dict.script_cyr || c == dict.script_lat || c == dict.script_neu {
                latch = if c == dict.script_cyr {
                    Script::Cyrillic
                } else if c == dict.script_lat {
                    Script::Latin
                } else {
                    Script::Neutral
                };
                i += 1;
            } else if c == dict.case_lower || c == dict.case_cap || c == dict.case_upper {
                assert!(dict.chord_to_word.contains_key(&chords[i + 1].mask()));
                i += 2;
            } else if dict.chord_to_punct.contains_key(&c.mask()) {
                i += 1;
            } else {
                assert!(dict.chord_to_word.contains_key(&c.mask()), "аккорд слова");
                let _ = latch;
                i += 1;
            }
        }
        assert_eq!(i, chords.len(), "структура потока без остатка");
        assert_ne!(latch, Script::Neutral);
    }

    #[test]
    fn test_empty_and_space_encodings() {
        let dict = StenoDictionary::build_default().unwrap();
        let chords = dict.encode_to_chords("").unwrap();
        assert!(chords.is_empty());
        assert_eq!(dict.decode_from_chords(&chords).unwrap(), "");
        let packed = pack_bytes(&[]);
        assert_eq!(packed, vec![0, 0, 0, 0]);
        assert_eq!(unpack_bytes(&packed).unwrap(), Vec::<Chord>::new());

        let chords = dict.encode_to_chords(" ").unwrap();
        assert_eq!(chords, vec![dict.space_chord()]);
        assert_eq!(unpack_bytes(&pack_bytes(&chords)).unwrap(), chords);
    }

    #[test]
    fn test_packed_widths() {
        let dict = StenoDictionary::build_default().unwrap();
        // словарное слово в нижнем регистре: 15 бит -> 2 байта
        let chords = dict.encode_to_chords("мир").unwrap();
        assert_eq!(chords.len(), 1);
        let packed = pack_bytes(&chords);
        assert_eq!(packed.len(), 4 + 2);
        // fallback-слово из 18 байт: raw_run(15) + длина(15) + 36 нибблов(180)
        // = 210 бит = 27 байт
        let chords = dict.encode_to_chords("эльбрусик").unwrap();
        assert_eq!(chords.len(), 2 + 36);
        let packed = pack_bytes(&chords);
        assert_eq!(packed.len(), 4 + 27);
    }

    #[test]
    fn test_property_lcg_roundtrip() {
        let dict = StenoDictionary::build_default().unwrap();
        let pool: &[&str] = &[
            "привет", "мир", "the", "rust", "и", "не", "проверка", "аккорд",
            "эльбрусик", "xyzzy", "2026", "7", "FooBar", "kо", "🚀", "日本語",
            "Тест", "ТЕСТ", "test", "Test", "№", "«»", "—", "с", "c", "но",
            "no", "найти", "z", "Ёё",
        ];
        let mut state = 0x2026_1121_u64;
        for _ in 0..400 {
            let mut text = String::new();
            let parts = 1 + (state >> 33) % 6;
            for _ in 0..parts {
                state = state
                    .wrapping_mul(6364136223846793005)
                    .wrapping_add(1442695040888963407);
                text.push_str(pool[(state >> 33) as usize % pool.len()]);
                state = state
                    .wrapping_mul(6364136223846793005)
                    .wrapping_add(1442695040888963407);
                match (state >> 33) % 5 {
                    0 => text.push_str(", "),
                    1 => text.push(' '),
                    2 => text.push_str(" — "),
                    3 => text.push_str(".\n"),
                    _ => text.push('\t'),
                }
            }
            let chords = dict.encode_to_chords(&text).unwrap();
            let packed = pack_bytes(&chords);
            let decoded = dict
                .decode_from_chords(&unpack_bytes(&packed).unwrap())
                .unwrap();
            assert_eq!(decoded, text, "property roundtrip failed for {text:?}");
        }
    }
}
