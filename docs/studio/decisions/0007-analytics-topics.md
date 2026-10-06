# ADR 0007 — Аналитика и предложения тем

- `studio track`: `scheduled→published` по publishAt, затем снимки статистики (append-only) для вышедших.
  YouTube Data API — просмотры/лайки/комментарии; YouTube Analytics (опционально) — средний просмотр,
  % досмотра, доход (`TS_MONETIZED=true`). Ошибка Analytics не валит сбор.
- `studio report`: темы (длинные), типы сцен в длинных (взвешено долей текста сцены), типы сцен
  в шортсах (сцена шортса), хуки длинных и шортсов. Берётся последний снимок каждой публикации.
- `--recommendations` пишет `data/studio/reports/recommendations-*.md`. Промпты не меняются автоматически.
- `studio topic suggest` → `data/studio/topics/suggestions-*.yaml`; в бэклог — только `studio topic accept`.
