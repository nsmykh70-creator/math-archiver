//! Тесты побайтового roundtrip конвейера UHC2.
//!
//! Запуск: cargo test (из корня воркспейса)

use uhc_core::{compress_parallel, decompress_parallel, CompressionMode, DEFAULT_BLOCK_SIZE};

fn roundtrip(data: &[u8], mode: CompressionMode, level: i32) -> Vec<u8> {
    let packed = compress_parallel(data, mode, DEFAULT_BLOCK_SIZE, level).expect("compress");
    decompress_parallel(&packed).expect("decompress")
}

#[test]
fn mode0_lossless_everything() {
    let ru = "Быстрая коричневая лиса прыгает через ленивую собаку, снова и снова.";
    let journal = "100\n+15\n*3\n-20\n+7\n*2\n";
    let cjk = "森林里的鸟看光，城市的光走水路。森林里的鸟看光，城市的光走水路。";
    let binary: Vec<u8> = (0..1000u32).map(|i| (i * 2654435761 % 256) as u8).collect();

    for (name, data) in [
        ("ru", ru.as_bytes()),
        ("journal", journal.as_bytes()),
        ("cjk", cjk.as_bytes()),
        ("binary", &binary),
        ("empty", b"".as_slice()),
    ] {
        assert_eq!(roundtrip(data, CompressionMode::Lossless, 5), data, "kind={name}");
    }
}

#[test]
fn mode0_multi_block_roundtrip() {
    let sentence = "Тихий утренний лес ждёт первый свет. ".repeat(10_000); // ~370 КБ, 3 блока
    let data = sentence.as_bytes();
    assert_eq!(roundtrip(data, CompressionMode::Lossless, 5), data);
}

#[test]
fn mode1_delta_journal_roundtrip() {
    let journal = "100\n+15\n*3\n-20\n+7\n*2\n+999\n*9\n-1234\n";
    assert_eq!(roundtrip(journal.as_bytes(), CompressionMode::ReadablePrune, 5), journal.as_bytes());
}

#[test]
fn mode1_text_is_deterministic_lossy_skeleton() {
    // Режимы 1/2 для текста — осознанно ПОТЕРЬНЫЙ «скелет» (транслит + прореживание):
    // декомпрессия обязана пройти (хеш контейнера считается по восстановимому
    // потоку), быть детерминированной, но НЕ обязана совпадать с исходником.
    let data = "Быстрая коричневая лиса прыгает через ленивую собаку снова и снова";
    let once = roundtrip(data.as_bytes(), CompressionMode::ReadablePrune, 5);
    let twice = roundtrip(data.as_bytes(), CompressionMode::ReadablePrune, 5);
    assert_eq!(once, twice, "декомпрессия должна быть детерминированной");
    assert_ne!(once, data.as_bytes(), "скелет отличается от исходника");
}

#[test]
fn mode2_aggressive_journal_roundtrip() {
    let journal = "42\n+58\n*7\n-100\n/4\n*2\n";
    assert_eq!(roundtrip(journal.as_bytes(), CompressionMode::Aggressive, 5), journal.as_bytes());
}

#[test]
fn container_checksum_detects_corruption() {
    let data = "Контроль целостности BLAKE3 обязан ловить повреждение байта.".repeat(50);
    let packed = compress_parallel(data.as_bytes(), CompressionMode::Lossless, DEFAULT_BLOCK_SIZE, 5)
        .expect("compress");
    let mut corrupted = packed.clone();
    let mid = corrupted.len() / 2;
    corrupted[mid] ^= 0x01;
    assert!(decompress_parallel(&corrupted).is_err(), "повреждение должно ловиться");
}
