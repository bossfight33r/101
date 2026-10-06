# ADR 0001 — TechStudio строится с нуля в репозитории 101

**Контекст.** ТЗ предполагало переиспользование ClipFactory импортом. Репозиторий `bossfight33r/101`
пуст; ClipFactory живёт в `bossfight33r/100`. Босс явно сказал: «не продолжай, с нуля начинай в 101».

**Решение.** Код ClipFactory не копируется и не импортируется. Инфраструктура, которую ТЗ просило
взять из ClipFactory, реализована в `src/techstudio/core/` теми же паттернами и правилами:
ffmpeg только через `core/ffmpeg.py`, probe и валидация, encoder backends (x264 / videotoolbox),
`LocalStorage`, манифесты и кеш этапов по хешам, structlog, SQLite, LLM- и ASR-бэкенды с фейками,
ASS-субтитры. Общие контракты (`Word`, `Publication`, `StatsSnapshot`) — в `techstudio/schemas.py`.
Очередь — inline (без Redis): один пользователь, видео в день — единицы.

**Последствия.** Если позже ClipFactory попадёт в этот репо, `core/*` заменяется импортами
`clipfactory.*` с тем же интерфейсом; правила CLAUDE.md уже совпадают.
