# CHANGELOG

## TechStudio

### Фаза 0 — Foundation
- Пакет `techstudio`, CLI `studio` (`doctor`, `topic add|list|import`).
- Контракты `schemas.py`: Channel, Topic, Script и сцены (discriminated union), артефакты этапов, статусы.
- `core/`: ffmpeg-обёртка, probe/валидация, энкодеры, LocalStorage, манифесты, structlog, SQLite, LLM (Anthropic/Fake), ASR (faster-whisper/mlx/Fake).
- Фейки: FakeLLM, FakeTTS, FakeTranscriber, FakeRenderer.
- Конфиги-примеры канала, тем, голосов; Dockerfile песочницы (VHS + сетевые утилиты, non-root).
- docs/studio, ADR 0001–0002.
