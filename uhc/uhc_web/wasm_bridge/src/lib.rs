use blake3::Hasher;
use flate2::write::DeflateEncoder;
use flate2::read::DeflateDecoder;
use flate2::Compression;
use std::io::{Read, Write};
use wasm_bindgen::prelude::*;

const MAGIC: &[u8; 4] = b"UHCW";

#[wasm_bindgen]
#[repr(u8)]
#[derive(Clone, Copy, PartialEq, Eq)]
pub enum WasmMode {
    Lossless = 0,
    ReadablePrune = 1,
    Aggressive = 2,
}

#[wasm_bindgen]
#[repr(u8)]
#[derive(Clone, Copy, PartialEq, Eq)]
pub enum WasmKind {
    Raw = 0,
    AlphaText = 1,
    IdeographText = 2,
    DeltaSeries = 3,
}

fn detect_kind(chunk: &[u8]) -> WasmKind {
    let Ok(text) = std::str::from_utf8(chunk) else {
        return WasmKind::Raw;
    };

    let mut delta_like = 0usize;
    let mut total_lines = 0usize;
    for line in text.lines() {
        let t = line.trim();
        if t.is_empty() {
            continue;
        }
        total_lines += 1;
        let b0 = t.as_bytes()[0];
        if matches!(b0, b'+' | b'-' | b'*' | b'/') && t[1..].chars().all(|c| c.is_ascii_digit()) {
            delta_like += 1;
        }
    }
    if total_lines >= 4 && delta_like * 10 >= total_lines * 7 {
        return WasmKind::DeltaSeries;
    }

    let mut cjk_or_kana = 0usize;
    let mut total = 0usize;
    for ch in text.chars().take(4096) {
        total += 1;
        let code = ch as u32;
        if (0x4E00..=0x9FFF).contains(&code) || (0x3040..=0x30FF).contains(&code) {
            cjk_or_kana += 1;
        }
    }
    if total > 0 && cjk_or_kana * 10 >= total * 3 {
        WasmKind::IdeographText
    } else {
        WasmKind::AlphaText
    }
}

fn encode_varint_u64(mut val: u64, out: &mut Vec<u8>) {
    while val >= 0x80 {
        out.push(((val as u8) & 0x7F) | 0x80);
        val >>= 7;
    }
    out.push(val as u8);
}

fn decode_varint_u64(buf: &[u8], off: &mut usize) -> Result<u64, String> {
    let mut res = 0u64;
    let mut shift = 0u32;
    loop {
        if *off >= buf.len() {
            return Err("unexpected end of varint".into());
        }
        let byte = buf[*off];
        *off += 1;
        if shift >= 64 {
            return Err("varint overflow".into());
        }
        res |= ((byte & 0x7F) as u64) << shift;
        if (byte & 0x80) == 0 {
            return Ok(res);
        }
        shift += 7;
    }
}

fn zigzag_enc(n: i64) -> u64 {
    ((n << 1) ^ (n >> 63)) as u64
}

fn zigzag_dec(z: u64) -> i64 {
    ((z >> 1) as i64) ^ (-((z & 1) as i64))
}

fn pack_delta(text: &str) -> Result<Vec<u8>, String> {
    let mut lines = text.lines().map(str::trim).filter(|l| !l.is_empty());
    let first = lines.next().ok_or("empty delta series")?;
    let x0: i64 = first.parse().map_err(|_| "bad initial value")?;
    let mut ops: Vec<(u8, u64)> = Vec::new();
    for line in lines {
        let (op_c, num_s) = line.split_at(1);
        let op_code = match op_c {
            "+" => 0u8,
            "-" => 1u8,
            "*" => 2u8,
            "/" => 3u8,
            _ => return Err("unknown delta operator".into()),
        };
        let step: u64 = num_s.trim().parse().map_err(|_| "bad delta step")?;
        ops.push((op_code, step));
    }
    let mut out = Vec::new();
    encode_varint_u64(zigzag_enc(x0), &mut out);
    encode_varint_u64(ops.len() as u64, &mut out);
    for (op, step) in ops {
        out.push(op);
        encode_varint_u64(step, &mut out);
    }
    Ok(out)
}

fn unpack_delta(bin: &[u8]) -> Result<String, String> {
    let mut off = 0usize;
    let x0 = zigzag_dec(decode_varint_u64(bin, &mut off)?);
    let count = decode_varint_u64(bin, &mut off)? as usize;
    let mut s = String::new();
    s.push_str(&format!("{x0}\n"));
    for _ in 0..count {
        if off >= bin.len() {
            return Err("truncated delta stream".into());
        }
        let op = bin[off];
        off += 1;
        let step = decode_varint_u64(bin, &mut off)?;
        let sym = match op {
            0 => '+',
            1 => '-',
            2 => '*',
            3 => '/',
            _ => return Err("invalid delta op".into()),
        };
        s.push_str(&format!("{sym}{step}\n"));
    }
    Ok(s)
}

fn translit_cyr(c: char) -> Option<&'static str> {
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

fn is_vowel_lat(c: char) -> bool {
    matches!(c.to_ascii_lowercase(), 'a' | 'e' | 'i' | 'o' | 'u' | 'y')
}

fn prune_word(word: &str, mode: WasmMode) -> String {
    let chars: Vec<char> = word.chars().collect();
    if chars.len() <= 4 || !chars.iter().any(|c| c.is_alphabetic()) {
        return word.to_string();
    }
    let keep_pre = match mode {
        WasmMode::Lossless => return word.to_string(),
        WasmMode::ReadablePrune => 2.min(chars.len()),
        WasmMode::Aggressive => 1.min(chars.len()),
    };
    let last = *chars.last().unwrap();
    let mut out = String::with_capacity(chars.len());
    for &c in &chars[..keep_pre] {
        out.push(c);
    }
    let mut prev_c: Option<char> = None;
    for &c in &chars[keep_pre..chars.len() - 1] {
        if c.is_alphabetic() {
            if is_vowel_lat(c) {
                continue;
            }
            let low = c.to_ascii_lowercase();
            if prev_c == Some(low) {
                continue;
            }
            prev_c = Some(low);
            out.push(c);
        } else {
            out.push(c);
        }
    }
    if chars.len() > keep_pre {
        out.push(last);
    }
    out
}

fn preprocess_chunk(chunk: &[u8], kind: WasmKind, mode: WasmMode) -> Vec<u8> {
    if mode == WasmMode::Lossless {
        return chunk.to_vec();
    }
    match kind {
        WasmKind::DeltaSeries => {
            if let Ok(t) = std::str::from_utf8(chunk) {
                if let Ok(p) = pack_delta(t) {
                    return p;
                }
            }
            chunk.to_vec()
        }
        WasmKind::AlphaText => {
            let Ok(t) = std::str::from_utf8(chunk) else {
                return chunk.to_vec();
            };
            let mut lat = String::with_capacity(t.len());
            for ch in t.chars() {
                if let Some(tr) = translit_cyr(ch) {
                    lat.push_str(tr);
                } else {
                    lat.push(ch);
                }
            }
            lat.split(' ')
                .map(|w| prune_word(w, mode))
                .collect::<Vec<_>>()
                .join(" ")
                .into_bytes()
        }
        WasmKind::IdeographText => {
            let Ok(t) = std::str::from_utf8(chunk) else {
                return chunk.to_vec();
            };
            t.chars()
                .filter(|&c| {
                    let code = c as u32;
                    let is_ar_mark = (0x0640..=0x065F).contains(&code) || code == 0x0670;
                    let is_part = matches!(
                        c,
                        '的' | '在' | '着' | '和' | '与' | 'の' | 'が' | 'を' | 'に' | 'は' | 'と' | 'で'
                    );
                    !is_ar_mark && !is_part
                })
                .collect::<String>()
                .into_bytes()
        }
        WasmKind::Raw => chunk.to_vec(),
    }
}

fn deflate_bytes(data: &[u8], level: u32) -> Result<Vec<u8>, String> {
    let mut enc = DeflateEncoder::new(Vec::new(), Compression::new(level.min(9)));
    enc.write_all(data).map_err(|e| e.to_string())?;
    enc.finish().map_err(|e| e.to_string())
}

fn inflate_bytes(data: &[u8]) -> Result<Vec<u8>, String> {
    let mut dec = DeflateDecoder::new(data);
    let mut out = Vec::new();
    dec.read_to_end(&mut out).map_err(|e| e.to_string())?;
    Ok(out)
}

#[wasm_bindgen]
pub fn compress_uhc_wasm(
    input: &[u8],
    mode_u8: u8,
    block_size: usize,
    level: u32,
) -> Result<Vec<u8>, JsValue> {
    let mode = match mode_u8 {
        0 => WasmMode::Lossless,
        1 => WasmMode::ReadablePrune,
        2 => WasmMode::Aggressive,
        _ => return Err(JsValue::from_str("Invalid mode")),
    };

    let bsize = block_size.max(1024);
    let chunks: Vec<&[u8]> = input.chunks(bsize).collect();

    // Хеш контейнера считается по потоку, который вернёт декомпрессор
    // (для mode 0 — исходник; для lossy-режимов 1/2 — детерминированный
    // «скелет»), чтобы декомпрессия не падала и оставалась проверяемой.
    let mut stream_hasher = Hasher::new();
    let mut out = Vec::new();
    out.extend_from_slice(MAGIC);
    out.extend_from_slice(&(chunks.len() as u32).to_le_bytes());

    for ch in chunks {
        let kind = detect_kind(ch);
        let prepared = preprocess_chunk(ch, kind, mode);
        let reconstructed = if kind == WasmKind::DeltaSeries && mode != WasmMode::Lossless {
            unpack_delta(&prepared)?.into_bytes()
        } else {
            prepared.clone()
        };
        stream_hasher.update(&reconstructed);
        let b_hash = blake3::hash(&prepared);
        let raw_len = prepared.len() as u32;
        let comp = deflate_bytes(&prepared, level).map_err(|e| JsValue::from_str(&e))?;
        let (flags, body) = if comp.len() < prepared.len() {
            (1u8, comp)
        } else {
            (0u8, prepared)
        };
        let body_len = body.len() as u32;

        // [kind:1][mode:1][flags:1][raw_len:4][body_len:4][blake3:32][body]
        out.push(kind as u8);
        out.push(mode as u8);
        out.push(flags);
        out.extend_from_slice(&raw_len.to_le_bytes());
        out.extend_from_slice(&body_len.to_le_bytes());
        out.extend_from_slice(b_hash.as_bytes());
        out.extend_from_slice(&body);
    }

    out.extend_from_slice(stream_hasher.finalize().as_bytes());
    Ok(out)
}

#[wasm_bindgen]
pub fn decompress_uhc_wasm(archive: &[u8]) -> Result<Vec<u8>, JsValue> {
    if archive.len() < 8 + 32 || &archive[0..4] != MAGIC {
        return Err(JsValue::from_str("Invalid UHCW archive header"));
    }
    let block_count = u32::from_le_bytes(archive[4..8].try_into().unwrap()) as usize;
    let mut off = 8usize;
    let mut out = Vec::new();

    for _ in 0..block_count {
        if archive.len().saturating_sub(off) < 43 {
            return Err(JsValue::from_str("Truncated block header"));
        }
        let kind = match archive[off] {
            0 => WasmKind::Raw,
            1 => WasmKind::AlphaText,
            2 => WasmKind::IdeographText,
            3 => WasmKind::DeltaSeries,
            _ => return Err(JsValue::from_str("Unknown block kind")),
        };
        let mode = match archive[off + 1] {
            0 => WasmMode::Lossless,
            1 => WasmMode::ReadablePrune,
            2 => WasmMode::Aggressive,
            _ => return Err(JsValue::from_str("Unknown block mode")),
        };
        let flags = archive[off + 2];
        let _raw_len = u32::from_le_bytes(archive[off + 3..off + 7].try_into().unwrap()) as usize;
        let body_len = u32::from_le_bytes(archive[off + 7..off + 11].try_into().unwrap()) as usize;
        let expected_hash: [u8; 32] = archive[off + 11..off + 43].try_into().unwrap();
        off += 43;

        if archive.len().saturating_sub(off) < body_len {
            return Err(JsValue::from_str("Truncated block body"));
        }
        let body = &archive[off..off + body_len];
        off += body_len;

        let prepared = if (flags & 1) == 1 {
            inflate_bytes(body).map_err(|e| JsValue::from_str(&e))?
        } else {
            body.to_vec()
        };

        if blake3::hash(&prepared).as_bytes() != &expected_hash {
            return Err(JsValue::from_str("Block BLAKE3 checksum mismatch"));
        }

        if kind == WasmKind::DeltaSeries && mode != WasmMode::Lossless {
            let s = unpack_delta(&prepared).map_err(|e| JsValue::from_str(&e))?;
            out.extend_from_slice(s.as_bytes());
        } else {
            out.extend_from_slice(&prepared);
        }
    }

    if archive.len().saturating_sub(off) < 32 {
        return Err(JsValue::from_str("Missing container BLAKE3 trailer"));
    }
    let expected_stream_hash: [u8; 32] = archive[off..off + 32].try_into().unwrap();
    let mut hasher = Hasher::new();
    hasher.update(&out);
    if hasher.finalize().as_bytes() != &expected_stream_hash {
        return Err(JsValue::from_str("Container BLAKE3 checksum mismatch"));
    }

    Ok(out)
}
