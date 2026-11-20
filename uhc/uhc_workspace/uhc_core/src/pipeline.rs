use crate::preprocess::{detect_kind, preprocess_block};
use crate::types::{CompressionMode, DataKind, UhcError};
use crate::varint::unpack_delta_lines;
use blake3::Hasher;
use rayon::prelude::*;

const MAGIC: &[u8; 4] = b"UHC2";
pub const DEFAULT_BLOCK_SIZE: usize = 128 * 1024; // 128 КБ
const BLOCK_HEADER_LEN: usize = 1 + 1 + 1 + 4 + 4 + 32; // 43 байта

fn encode_block(
    chunk: &[u8],
    mode: CompressionMode,
    zstd_level: i32,
) -> Result<(Vec<u8>, Vec<u8>), UhcError> {
    let kind = detect_kind(chunk);
    let prepared = preprocess_block(chunk, kind, mode);
    let block_hash = blake3::hash(&prepared);
    let raw_len = prepared.len() as u32;

    // Поток, который действительно вернёт декодер: для дельта-журнала —
    // восстановленный журнал, для mode 0 — сам исходник. Хеш контейнера
    // считается именно по нему: для mode 0 он совпадает с хешем исходника,
    // а для lossy-режимов (1/2) декомпрессия не падает и остаётся детерминированной.
    let reconstructed = if kind == DataKind::DeltaSeries && mode != CompressionMode::Lossless {
        unpack_delta_lines(&prepared)?.into_bytes()
    } else {
        prepared.clone()
    };

    let compressed = zstd::bulk::compress(&prepared, zstd_level)
        .map_err(|e| UhcError::Codec(e.to_string()))?;

    let (flags, body) = if compressed.len() < prepared.len() {
        (1u8, compressed)
    } else {
        (0u8, prepared)
    };

    let body_len = body.len() as u32;
    let mut frame = Vec::with_capacity(BLOCK_HEADER_LEN + body.len());
    frame.push(kind as u8);
    frame.push(mode as u8);
    frame.push(flags);
    frame.extend_from_slice(&raw_len.to_le_bytes());
    frame.extend_from_slice(&body_len.to_le_bytes());
    frame.extend_from_slice(block_hash.as_bytes());
    frame.extend_from_slice(&body);
    Ok((frame, reconstructed))
}

fn decode_block(frame: &[u8], offset: &mut usize) -> Result<Vec<u8>, UhcError> {
    if frame.len().saturating_sub(*offset) < BLOCK_HEADER_LEN {
        return Err(UhcError::InvalidHeader("truncated block header".into()));
    }

    let kind = DataKind::from_u8(frame[*offset])?;
    let mode = CompressionMode::from_u8(frame[*offset + 1])?;
    let flags = frame[*offset + 2];
    let raw_len = u32::from_le_bytes(frame[*offset + 3..*offset + 7].try_into().unwrap()) as usize;
    let body_len = u32::from_le_bytes(frame[*offset + 7..*offset + 11].try_into().unwrap()) as usize;
    let expected_hash: [u8; 32] = frame[*offset + 11..*offset + 43].try_into().unwrap();
    *offset += BLOCK_HEADER_LEN;

    if frame.len().saturating_sub(*offset) < body_len {
        return Err(UhcError::InvalidHeader("truncated block payload".into()));
    }

    let body = &frame[*offset..*offset + body_len];
    *offset += body_len;

    let prepared = if (flags & 1) == 1 {
        zstd::bulk::decompress(body, raw_len.max(64 * 1024))
            .map_err(|e| UhcError::Codec(e.to_string()))?
    } else {
        body.to_vec()
    };

    let actual_hash = blake3::hash(&prepared);
    if actual_hash.as_bytes() != &expected_hash {
        return Err(UhcError::ChecksumMismatch(
            "block BLAKE3 checksum failed".into(),
        ));
    }

    if kind == DataKind::DeltaSeries && mode != CompressionMode::Lossless {
        let unpacked_text = unpack_delta_lines(&prepared)?;
        Ok(unpacked_text.into_bytes())
    } else {
        Ok(prepared)
    }
}

pub fn compress_parallel(
    input: &[u8],
    mode: CompressionMode,
    block_size: usize,
    zstd_level: i32,
) -> Result<Vec<u8>, UhcError> {
    let bsize = block_size.max(4096);
    let chunks: Vec<&[u8]> = input.chunks(bsize).collect();

    let encoded_blocks: Result<Vec<(Vec<u8>, Vec<u8>)>, UhcError> = chunks
        .into_par_iter()
        .map(|ch| encode_block(ch, mode, zstd_level))
        .collect();

    let blocks = encoded_blocks?;
    let mut hasher = Hasher::new();
    let mut total_size: usize = MAGIC.len() + 4 + 32;
    for (frame, reconstructed) in &blocks {
        hasher.update(reconstructed);
        total_size += frame.len();
    }
    let stream_hash = hasher.finalize();

    let mut out = Vec::with_capacity(total_size);
    out.extend_from_slice(MAGIC);
    out.extend_from_slice(&(blocks.len() as u32).to_le_bytes());
    for (frame, _) in &blocks {
        out.extend_from_slice(frame);
    }
    out.extend_from_slice(stream_hash.as_bytes());
    Ok(out)
}

pub fn decompress_parallel(archive: &[u8]) -> Result<Vec<u8>, UhcError> {
    if archive.len() < 8 + 32 || &archive[0..4] != MAGIC {
        return Err(UhcError::InvalidHeader("bad UHC2 magic bytes".into()));
    }
    let block_count = u32::from_le_bytes(archive[4..8].try_into().unwrap()) as usize;
    let mut offset = 8usize;
    let mut slices = Vec::with_capacity(block_count);

    for _ in 0..block_count {
        let start = offset;
        let _ = decode_block(archive, &mut offset)?;
        slices.push(&archive[start..offset]);
    }

    if archive.len().saturating_sub(offset) < 32 {
        return Err(UhcError::InvalidHeader("missing container BLAKE3 trailer".into()));
    }
    let expected_stream_hash: [u8; 32] = archive[offset..offset + 32].try_into().unwrap();

    let decoded: Result<Vec<Vec<u8>>, UhcError> = slices
        .into_par_iter()
        .map(|sl| {
            let mut local_off = 0usize;
            decode_block(sl, &mut local_off)
        })
        .collect();

    let parts = decoded?;
    let mut out = Vec::with_capacity(parts.iter().map(|p| p.len()).sum());
    for p in parts {
        out.extend_from_slice(&p);
    }

    let mut hasher = Hasher::new();
    hasher.update(&out);
    if hasher.finalize().as_bytes() != &expected_stream_hash {
        return Err(UhcError::ChecksumMismatch(
            "container BLAKE3 checksum failed".into(),
        ));
    }

    Ok(out)
}
