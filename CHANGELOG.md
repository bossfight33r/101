# CHANGELOG

## TechStudio

### Фаза 4 — Ревью и публикация
- Бот TechStudio (aiogram, только TS_ADMIN_IDS): гейт 1 (Approve / правка YAML / перегенерация сцены), гейт 2 (превью, шортсы, 3 миниатюры, Approve / Reject / перерендер сцены), команды /studio /topics /new /review /status /retry /publish.
- Публикация на YouTube: private + publishAt, главы и footer в описании, SRT, миниатюра (экспорт при ошибке), шортсы после длинного с интервалом, идемпотентный повтор.
- Scheduler: локальное время канала, DST, дневные лимиты.
- CLI `studio review|publish|auth youtube|bot`.

### Фаза 3 — Озвучка и сборка
- Озвучка: словарь произношения только для TTS, Piper/Fake, loudnorm голоса, пословные тайминги через ASR + выравнивание к исходному тексту.
- Тайминг: max(озвучка + паузы, min_sec, минимум визуала); freeze (tpad) / обрезка хвоста, озвучка не режется.
- Длинное видео 1920x1080 30fps: сегменты сцен, cut/fade, музыка с ducking (sidechaincompress), loudnorm -14, SRT отдельно, главы по правилам YouTube.
- Шортсы 9:16: карточка хука (отдельная озвучка), сцена, end-card, ASS-субтитры с подсветкой слова, ≤ 60 с.
- 3 миниатюры, метаданные через LLM, сжатое превью для ревью.
- Манифесты и resume: `studio render|status|retry`, перерендер одной сцены (ADR 0005).

### Фаза 2 — Визуалы
- Рендереры terminal (VHS tape → Docker-песочница → нормализация), code (Pygments + Pillow, by_line, подсветка строк, перенос в 9:16), diagram (mermaid-cli локально/в Docker, fallback-слайд), slide (буллеты по одному), image (Ken Burns, fallback при отсутствии ассета). Обе ориентации нативно.
- `sandbox/docker.py`: non-root, без сети, read-only, cap-drop, лимиты и таймаут.
- replay: вывод из файла реального вывода через bash DEBUG trap (ADR 0004).
- Проверка mermaid реальным mermaid-cli при валидации, если доступен.

### Фаза 1 — Сценарий
- Генерация сценария через LLM (промпт `prompts/script.md` + `script-format.md`), одна попытка самоисправления.
- Валидация: хук ≤ 10 с, длительность против окна канала, запрещённые фразы, шортсы ≤ 58 с, mermaid, ассеты, policy.
- `sandbox/policy.py`: денилист опасных команд, секреты, сеть только с `network: true`.
- YAML round-trip с шапкой ревью (флаги network/replay, проблемы), версии `versions/script.vN.yaml`.
- CLI `studio script new|export|import|approve|regen`; approve фиксирует хеш, orchestrator не рендерит без него.

### Фаза 0 — Foundation
- Пакет `techstudio`, CLI `studio` (`doctor`, `topic add|list|import`).
- Контракты `schemas.py`: Channel, Topic, Script и сцены (discriminated union), артефакты этапов, статусы.
- `core/`: ffmpeg-обёртка, probe/валидация, энкодеры, LocalStorage, манифесты, structlog, SQLite, LLM (Anthropic/Fake), ASR (faster-whisper/mlx/Fake).
- Фейки: FakeLLM, FakeTTS, FakeTranscriber, FakeRenderer.
- Конфиги-примеры канала, тем, голосов; Dockerfile песочницы (VHS + сетевые утилиты, non-root).
- docs/studio, ADR 0001–0002.
