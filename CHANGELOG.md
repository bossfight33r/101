# CHANGELOG

## TechStudio

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
