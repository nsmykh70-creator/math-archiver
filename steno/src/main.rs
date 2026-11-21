//! Демонстрация: словарь, формат аккорда, битовая упаковка и проверка
//! полного совпадения при обратном декодировании.

use steno::{pack_bytes, unpack_bytes, Chord, StenoDictionary};

fn demo(dict: &StenoDictionary, label: &str, sample: &str) -> (usize, usize) {
    let chords = dict.encode_to_chords(sample).expect("encode");
    let packed = pack_bytes(&chords);
    let unpacked = unpack_bytes(&packed).expect("unpack");
    let restored = dict.decode_from_chords(&unpacked).expect("decode");
    assert_eq!(restored, sample, "несовпадение для {label}");

    let preview: String = chords
        .iter()
        .take(10)
        .map(|c| format!("[{c}]"))
        .collect::<Vec<_>>()
        .join(" ");

    println!("=== {label} ===");
    println!("исходный текст : {sample:?}");
    println!("до             : {} байт", sample.len());
    println!("аккордов       : {} (первые: {preview})", chords.len());
    println!("после          : {} байт ({} бит + 4 Б заголовок)",
             packed.len(),
             (packed.len() - 4) * 8);
    println!("восстановлено  : {restored:?}");
    println!("совпадение 100%: {}\n", restored == sample);
    (sample.len(), packed.len())
}

fn main() {
    let dict = StenoDictionary::build_default().expect("словарь построен");

    println!("=== Модель ===");
    println!("клавиатура: клавиши 1..=24; аккорд = подмножество клавиш, u32-маска (бит k-1 = клавиша k)");
    println!("упаковка pack_bytes: [u32 BE число аккордов] + битовый поток (MSB-first):");
    println!("  одиночная клавиша      -> 5 бит (номер клавиши - 1)");
    println!("  аккорд из двух клавиш  -> код 25 + 2x5 бит (15 бит, ключи по возрастанию)");
    println!("  прочий аккорд          -> код 24 + 24 бита полной маски (29 бит)");
    println!("  хвостовые биты выравнивания — нули (проверяются при распаковке)");
    println!();
    println!("=== Раскладка маркеров и служебных аккордов ===");
    println!("клавиша 1 = пробел                  аккорд 1+2 = fallback-run (байты)");
    println!("клавиша 2 = регистр: нижний (по умолчанию, не пишется)");
    println!("клавиша 3 = регистр: Заглавный      аккорд 1+3 = fallback-byte (1 байт)");
    println!("клавиша 4 = регистр: ВЕРХНИЙ        клавиши 9..24 = нибблы 0..15 fallback-а");
    println!("клавиша 5 = алфавит: кириллица (защёлка, старт потока)");
    println!("клавиша 6 = алфавит: латиница (защёлка, пишется при смене)");
    println!("клавиша 7 = точка                   аккорд {} = алфавит «прочее» (резерв)", dict.script_neu_chord());
    println!("клавиша 8 = запятая");
    println!("слово = [защёлка алфавита?][регистр?][аккорд слова]");
    println!();
    println!("=== Словарь ===");
    println!("слов: {}, знаков: {} (пробел и запятая — одиночные клавиши)",
             dict.word_count(), dict.punct_count());
    println!("первые 15 слов (токен -> аккорд -> маска):");
    for (token, chord) in dict.words().into_iter().take(15) {
        println!("  {token:<14} -> {:<6} = {:#010x}", chord.to_string(), chord.mask());
    }
    println!("гомоглифы: «с» и «c» — ОДИН аккорд слова, алфавит различает защёлка;");
    let fmt = |cs: &[Chord]| cs.iter().map(|c| format!("[{c}]")).collect::<Vec<_>>().join("");
    let ru = dict.encode_to_chords("с то").unwrap();
    let en = dict.encode_to_chords("c to").unwrap();
    println!("  «с то» -> {}, «c to» -> {}", fmt(&ru), fmt(&en));
    println!("  «to» и «то», «he» и «не», «be» и «ве», «my» и «му» — общие аккорды");
    println!();

    let mut total_src = 0_usize;
    let mut total_packed = 0_usize;
    let samples: [(&str, &str); 5] = [
        ("Русский", "Привет, мир! Это код на Rust: проверка аккордов и стенографии."),
        ("Английский", "Hello, world! This is a Rust chord test with punctuation & 123."),
        ("Смешанный + гомоглифы", "Смешанный текст с k/o/А аналогами, 2026 год и эмодзи 🚀."),
        ("Сложный", "iPhone, FooBar, оО, kо, 日本語 Ω — всё восстановится!"),
        ("Длинный абзац",
         "Это проверка стенографии: данные превращаются в аккорды клавиатуры.\n\
          Частые слова занимают один аккорд, редкие — посимвольный fallback.\n\
          Регистр и алфавит восстанавливаются маркерами: РУСТ, Rust, rust!"),
    ];
    for (label, text) in samples {
        let (src, packed) = demo(&dict, label, text);
        total_src += src;
        total_packed += packed;
    }
    println!("=== Итог ===");
    println!("исходник: {} байт; закодировано: {} байт ({}%)",
             total_src,
             total_packed,
             total_packed * 100 / total_src.max(1));
    println!("словарь: {} слов + {} знаков; маркеры на клавишах 1..8; нибблы на 9..24",
             dict.word_count(), dict.punct_count());
    let _ = Chord::from_keys(&[1]); // демонстрация API аккордов
}
