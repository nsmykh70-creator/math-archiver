# UHC Web Version (Rust WASM + Browser UI)

Веб-версия архиватора **UHC**:
- `wasm_bridge/` — крейт на Rust (`wasm-bindgen` + `blake3` + `flate2`) с контейнером `UHCW`, детектором типа данных, дельта-упаковкой и контрольными суммами `BLAKE3`.
- `ui/` — веб-интерфейс (`index.html` + `app.js`) с drag-and-drop, выбором режима `0/1/2`, настройкой уровня сжатия и размера блока, метриками и скачиванием результата.

## Сборка WASM и запуск локально

1. Установите `wasm-pack` (`cargo install wasm-pack`) и цель `wasm32-unknown-unknown`:
   ```bash
   rustup target add wasm32-unknown-unknown
   ```
2. Соберите пакет в `uhc_web/ui/pkg`:
   ```bash
   cd uhc_web/wasm_bridge
   wasm-pack build --target web --out-dir ../ui/pkg
   ```
3. Запустите любой локальный статический сервер в папке `uhc_web/ui`:
   ```bash
   cd ../ui
   python3 -m http.server 8080
   ```
   и откройте `http://localhost:8080` в браузере.
