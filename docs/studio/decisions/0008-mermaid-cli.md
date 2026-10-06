# ADR 0008 — mermaid-cli: совместимые флаги, ориентация, ошибки

- mmdc 12 убрал `-w/-H`. Используем только общие для 10–12 флаги: `-i -o -b transparent -t dark -s N`;
  размер под кадр — Pillow (`contain`), чёткость — scale 3 для 1080p.
- 9:16: `flowchart/graph LR|RL` автоматически разворачивается в `TD|BT` — горизонтальная схема
  в вертикальном кадре нечитаема.
- Ошибка рендера показывается на ревью коротко: строки от `Error:` до стектрейса.
- Под root (CI/контейнер) Chromium требует `--no-sandbox`: `TS_MERMAID_PUPPETEER_CONFIG=<json>`
  с `executablePath` и `args` передаётся в `mmdc -p`. На Маке не нужен.
