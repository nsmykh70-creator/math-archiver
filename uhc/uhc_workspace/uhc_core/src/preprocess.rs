use crate::types::{CompressionMode, DataKind};
use crate::varint::pack_delta_lines;

pub fn detect_kind(chunk: &[u8]) -> DataKind {
    let text = match std::str::from_utf8(chunk) {
        Ok(s) => s,
        Err(_) => return DataKind::Raw,
    };

    let mut non_ascii_high = 0usize;
    let mut total_chars = 0usize;
    let mut delta_like_lines = 0usize;
    let mut total_lines = 0usize;

    for line in text.lines() {
        let trimmed = line.trim();
        if trimmed.is_empty() {
            continue;
        }
        total_lines += 1;
        let first = trimmed.as_bytes()[0];
        if matches!(first, b'+' | b'-' | b'*' | b'/')
            && trimmed[1..].chars().all(|c| c.is_ascii_digit())
        {
            delta_like_lines += 1;
        }
    }

    if total_lines >= 4 && delta_like_lines * 10 >= total_lines * 7 {
        return DataKind::DeltaSeries;
    }

    for ch in text.chars().take(4096) {
        total_chars += 1;
        let code = ch as u32;
        if (0x4E00..=0x9FFF).contains(&code) || (0x3040..=0x30FF).contains(&code) {
            non_ascii_high += 1;
        }
    }

    if total_chars > 0 && non_ascii_high * 10 >= total_chars * 3 {
        DataKind::IdeographText
    } else {
        DataKind::AlphaText
    }
}

fn is_vowel_latin(c: char) -> bool {
    matches!(
        c.to_ascii_lowercase(),
        'a' | 'e' | 'i' | 'o' | 'u' | 'y'
    )
}

fn translit_cyrillic_char(c: char) -> Option<&'static str> {
    Some(match c {
        'А' => "A", 'Б' => "B", 'В' => "V", 'Г' => "G", 'Д' => "D", 'Е' => "E", 'Ё' => "Yo",
        'Ж' => "Zh", 'З' => "Z", 'И' => "I", 'Й' => "Y", 'К' => "K", 'Л' => "L", 'М' => "M",
        'Н' => "N", 'О' => "O", 'П' => "P", 'Р' => "R", 'С' => "S", 'Т' => "T", 'У' => "U",
        'Ф' => "F", 'Х' => "Kh", 'Ц' => "Ts", 'Ч' => "Ch", 'Ш' => "Sh", 'Щ' => "Shch",
        'Ъ' | 'Ь' => "", 'Ы' => "Y", 'Э' => "E", 'Ю' => "Yu", 'Я' => "Ya",
        'а' => "a", 'б' => "b", 'в' => "v", 'г' => "g", 'д' => "d", 'е' => "e", 'ё' => "yo",
        'ж' => "zh", 'з' => "z", 'и' => "i", 'й' => "y", 'к' => "k", 'л' => "l", 'м' => "m",
        'н' => "n", 'о' => "o", 'п' => "p", 'р' => "r", 'с' => "s", 'т' => "t", 'у' => "u",
        'ф' => "f", 'х' => "kh", 'ц' => "ts", 'ч' => "ch", 'ш' => "sh", 'щ' => "shch",
        'ъ' | 'ь' => "", 'ы' => "y", 'э' => "e", 'ю' => "yu", 'я' => "ya",
        _ => return None,
    })
}

fn prune_alpha_word(word: &str, mode: CompressionMode) -> String {
    let chars: Vec<char> = word.chars().collect();
    if chars.len() <= 4 || !chars.iter().any(|c| c.is_alphabetic()) {
        return word.to_string();
    }

    let keep_prefix = match mode {
        CompressionMode::Lossless => return word.to_string(),
        CompressionMode::ReadablePrune => 2.min(chars.len()),
        CompressionMode::Aggressive => 1.min(chars.len()),
    };

    let last = *chars.last().unwrap();
    let mut out = String::with_capacity(chars.len());

    for &c in &chars[..keep_prefix] {
        out.push(c);
    }

    let mut prev_cons: Option<char> = None;
    for &c in &chars[keep_prefix..chars.len() - 1] {
        if c.is_alphabetic() {
            if is_vowel_latin(c) {
                continue;
            }
            let low = c.to_ascii_lowercase();
            if prev_cons == Some(low) {
                continue;
            }
            prev_cons = Some(low);
            out.push(c);
        } else {
            out.push(c);
        }
    }

    if chars.len() > keep_prefix {
        out.push(last);
    }
    out
}

pub fn preprocess_block(chunk: &[u8], kind: DataKind, mode: CompressionMode) -> Vec<u8> {
    if mode == CompressionMode::Lossless {
        return chunk.to_vec();
    }

    match kind {
        DataKind::DeltaSeries => {
            if let Ok(text) = std::str::from_utf8(chunk) {
                if let Ok(packed) = pack_delta_lines(text) {
                    return packed;
                }
            }
            chunk.to_vec()
        }
        DataKind::AlphaText => {
            let Ok(text) = std::str::from_utf8(chunk) else {
                return chunk.to_vec();
            };
            let mut latinized = String::with_capacity(text.len());
            for ch in text.chars() {
                if let Some(tr) = translit_cyrillic_char(ch) {
                    latinized.push_str(tr);
                } else {
                    latinized.push(ch);
                }
            }
            latinized
                .split(' ')
                .map(|w| prune_alpha_word(w, mode))
                .collect::<Vec<_>>()
                .join(" ")
                .into_bytes()
        }
        DataKind::IdeographText => {
            let Ok(text) = std::str::from_utf8(chunk) else {
                return chunk.to_vec();
            };
            text.chars()
                .filter(|&c| {
                    let code = c as u32;
                    let is_ar_mark = (0x0640..=0x065F).contains(&code) || code == 0x0670;
                    let is_common_particle = matches!(
                        c,
                        '的' | '在' | '着' | '和' | '与' | 'の' | 'が' | 'を' | 'に' | 'は' | 'と' | 'で'
                    );
                    !is_ar_mark && !is_common_particle
                })
                .collect::<String>()
                .into_bytes()
        }
        DataKind::Raw => chunk.to_vec(),
    }
}
