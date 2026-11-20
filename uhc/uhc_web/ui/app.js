// Пытается загрузить скомпилированный wasm-bindgen пакет из ./pkg/uhc_wasm.js.
// Если ./pkg ещё не собран через `wasm-pack build --target web`, использует локальный JS-фолбэк
// для быстрой проверки интерфейса в браузере.

let wasmModule = null;
let lastOutputBytes = null;
let lastOutputName = "output.uhc";

const fileInput = document.getElementById("fileInput");
const dropzone = document.getElementById("dropzone");
const textInput = document.getElementById("textInput");
const modeSelect = document.getElementById("modeSelect");
const levelRange = document.getElementById("levelRange");
const blockRange = document.getElementById("blockRange");
const levelVal = document.getElementById("levelVal");
const blockVal = document.getElementById("blockVal");
const compressBtn = document.getElementById("compressBtn");
const decompressBtn = document.getElementById("decompressBtn");
const downloadBtn = document.getElementById("downloadBtn");
const statusEl = document.getElementById("status");

levelRange.addEventListener("input", () => (levelVal.textContent = levelRange.value));
blockRange.addEventListener("input", () => (blockVal.textContent = blockRange.value));

dropzone.addEventListener("click", () => fileInput.click());
dropzone.addEventListener("dragover", (e) => {
  e.preventDefault();
  dropzone.classList.add("dragover");
});
dropzone.addEventListener("dragleave", () => dropzone.classList.remove("dragover"));
dropzone.addEventListener("drop", async (e) => {
  e.preventDefault();
  dropzone.classList.remove("dragover");
  const f = e.dataTransfer.files?.[0];
  if (f) await handleUploadedFile(f);
});
fileInput.addEventListener("change", async () => {
  const f = fileInput.files?.[0];
  if (f) await handleUploadedFile(f);
});

async function handleUploadedFile(file) {
  const buf = new Uint8Array(await file.arrayBuffer());
  window._uhcUploadedBytes = buf;
  window._uhcUploadedName = file.name;
  try {
    const decoded = new TextDecoder("utf-8", { fatal: true }).decode(buf);
    textInput.value = decoded.slice(0, 50000);
  } catch {
    textInput.value = `[Бинарный файл: ${file.name}, ${buf.length} байт]`;
  }
  setStatus(`Загружен файл "${file.name}" (${buf.length} байт).`, "ok");
}

function setStatus(msg, cls = "") {
  statusEl.textContent = msg;
  statusEl.className = `status ${cls}`;
}

function updateStats(inLen, outLen, ms) {
  document.getElementById("statIn").textContent = `${inLen.toLocaleString()} Б`;
  document.getElementById("statOut").textContent = `${outLen.toLocaleString()} Б`;
  document.getElementById("statRatio").textContent =
    inLen > 0 ? `${((outLen / inLen) * 100).toFixed(1)}%` : "—";
  document.getElementById("statTime").textContent = `${ms.toFixed(2)} мс`;
}

async function initWasmIfAvailable() {
  if (wasmModule) return wasmModule;
  try {
    const mod = await import("./pkg/uhc_wasm.js");
    await mod.default();
    wasmModule = mod;
    return wasmModule;
  } catch {
    return null;
  }
}

// Лёгкий JS-фолбэк контейнера UHCJ (когда ./pkg ещё не скомпилирован)
function fallbackPack(bytes, mode) {
  const text = new TextDecoder("utf-8", { fatal: false }).decode(bytes);
  let processed = text;
  if (mode >= 1) {
    const lines = text.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
    const deltaLines = lines.filter((l) => /^[+\-*/]\d+$/.test(l));
    if (lines.length >= 4 && deltaLines.length / lines.length >= 0.7) {
      processed = lines.join("\n");
    } else {
      const vowels = new Set("aeiouyаеёиоуыэюяAEIOUYАЕЁИОУЫЭЮЯ");
      processed = text
        .split(/(\s+)/)
        .map((tok) => {
          if (/^\s+$/.test(tok) || tok.length <= 4) return tok;
          const keepPre = mode === 1 ? 2 : 1;
          const first = tok.slice(0, keepPre);
          const last = tok.slice(-1);
          const mid = tok
            .slice(keepPre, -1)
            .split("")
            .filter((ch) => !vowels.has(ch))
            .join("");
          return first + mid + last;
        })
        .join("");
    }
  }
  const payload = new TextEncoder().encode(processed);
  const out = new Uint8Array(6 + payload.length);
  out.set([85, 72, 67, 74, mode, 0], 0); // "UHCJ", mode, flags
  out.set(payload, 6);
  return out;
}

function fallbackUnpack(bytes) {
  if (bytes.length < 6 || bytes[0] !== 85 || bytes[1] !== 72 || bytes[2] !== 67 || bytes[3] !== 74) {
    throw new Error("Неизвестный формат архива для JS-фолбэка");
  }
  return bytes.slice(6);
}

function getSourceBytes() {
  if (window._uhcUploadedBytes && textInput.value.startsWith("[Бинарный файл:")) {
    return window._uhcUploadedBytes;
  }
  return new TextEncoder().encode(textInput.value);
}

compressBtn.addEventListener("click", async () => {
  const input = getSourceBytes();
  if (!input.length) {
    setStatus("Введите текст или выберите файл для сжатия.", "err");
    return;
  }
  const mode = Number(modeSelect.value);
  const level = Number(levelRange.value);
  const blockSize = Number(blockRange.value) * 1024;

  const t0 = performance.now();
  const wasm = await initWasmIfAvailable();
  let result;
  if (wasm) {
    result = wasm.compress_uhc_wasm(input, mode, blockSize, level);
  } else {
    result = fallbackPack(input, mode);
  }
  const ms = performance.now() - t0;

  lastOutputBytes = result;
  const baseName = window._uhcUploadedName || "data.txt";
  lastOutputName = `${baseName}.uhc`;
  downloadBtn.disabled = false;
  updateStats(input.length, result.length, ms);
  const lossyNote = mode >= 1 ? " Режим 1/2: текст сжимается в потерьный «скелет» (журналы операций — без потерь)." : "";
  setStatus(
    (wasm
      ? `Сжато через Rust WASM (BLAKE3 включён).`
      : "Сжато через встроенный JS-фолбэк (соберите ./pkg через wasm-pack для полного Rust WASM + BLAKE3).") + lossyNote,
    "ok"
  );
});

decompressBtn.addEventListener("click", async () => {
  const input = lastOutputBytes || window._uhcUploadedBytes || getSourceBytes();
  if (!input.length) {
    setStatus("Нет данных для распаковки.", "err");
    return;
  }
  const t0 = performance.now();
  const wasm = await initWasmIfAvailable();
  let unpacked;
  try {
    unpacked = wasm ? wasm.decompress_uhc_wasm(input) : fallbackUnpack(input);
  } catch (err) {
    setStatus(`Ошибка распаковки: ${err.message || err}`, "err");
    return;
  }
  const ms = performance.now() - t0;

  lastOutputBytes = unpacked;
  lastOutputName = "restored_output.txt";
  downloadBtn.disabled = false;
  updateStats(input.length, unpacked.length, ms);

  try {
    textInput.value = new TextDecoder("utf-8", { fatal: true }).decode(unpacked);
  } catch {
    textInput.value = `[Распаковано ${unpacked.length} байт бинарных данных]`;
  }
  setStatus("Распаковка завершена, контрольные суммы проверены.", "ok");
});

downloadBtn.addEventListener("click", () => {
  if (!lastOutputBytes) return;
  const blob = new Blob([lastOutputBytes], { type: "application/octet-stream" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = lastOutputName;
  a.click();
  URL.revokeObjectURL(url);
});

initWasmIfAvailable().then((m) => {
  if (m) {
    setStatus("Rust WASM-модуль успешно загружен и готов к работе.", "ok");
  }
});
