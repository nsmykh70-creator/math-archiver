use std::env;
use std::fs;
use std::time::Instant;
use uhc_core::{compress_parallel, decompress_parallel, CompressionMode, DEFAULT_BLOCK_SIZE};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<String> = env::args().collect();
    if args.len() < 3 {
        eprintln!("Usage: uhc_cli <input_file> <0|1|2> [zstd_level]");
        std::process::exit(1);
    }

    let data = fs::read(&args[1])?;
    let mode = match args[2].as_str() {
        "0" => CompressionMode::Lossless,
        "1" => CompressionMode::ReadablePrune,
        "2" => CompressionMode::Aggressive,
        _ => return Err("mode must be 0, 1, or 2".into()),
    };
    let level: i32 = args.get(3).and_then(|s| s.parse().ok()).unwrap_or(5);

    let t0 = Instant::now();
    let packed = compress_parallel(&data, mode, DEFAULT_BLOCK_SIZE, level)?;
    let comp_ms = t0.elapsed().as_secs_f64() * 1000.0;

    let t1 = Instant::now();
    let unpacked = decompress_parallel(&packed)?;
    let dec_ms = t1.elapsed().as_secs_f64() * 1000.0;

    println!("Input:        {} bytes", data.len());
    println!(
        "Compressed:   {} bytes ({:.1}%) in {:.2} ms",
        packed.len(),
        packed.len() as f64 / data.len().max(1) as f64 * 100.0,
        comp_ms
    );
    println!("Decompressed: {} bytes in {:.2} ms", unpacked.len(), dec_ms);

    Ok(())
}
