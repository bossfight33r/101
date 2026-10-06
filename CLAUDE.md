# CLAUDE.md — правила работы в репозитории

Новая сессия начинает с чтения этого файла и `docs/studio/STATUS.md`.

## Общие правила
1. Не читать целиком медиа, `words.json`, логи ffmpeg и `refs/` — только head/tail/grep/range reads.
2. Не коммитить `data/`, медиа, `.env`, токены и секреты. Секреты — только env.
3. Данные между этапами — только через `src/techstudio/schemas.py`.
4. Внешние сервисы (LLM, Whisper, TTS, YouTube, Telegram) — только через `core/llm`, `core/transcriber`, `voice/`, `publish/`, `track/`, `bot/`.
5. ffmpeg/ffprobe — только через `src/techstudio/core/ffmpeg.py`. `subprocess` — только в обёртках из `per-file-ignores` S603 в `pyproject.toml`.
6. Этапы идемпотентны; кеш — только через манифест (`core/manifest.py`: inputs hash + stage_version + хеши выходов), не через `exists()`.
7. Работающие модули не переписывать без необходимости; изменение архитектуры — через ADR в `docs/studio/decisions/`.
8. В тестах никаких реальных API (YouTube, Telegram, Anthropic, TTS-API, интернет) и Docker.
9. Бот обслуживает только `TS_ADMIN_IDS`.
10. После каждой фазы: `make lint` → `make test` → `docs/studio/STATUS.md`, `CHANGELOG.md` → commit → push.

## TechStudio
- Команды из сценариев выполняются **только в Docker-песочнице** (`sandbox/docker.py`) и **только после `sandbox/policy.py`**. Сеть выключена, кроме сцен с явным `network: true`.
- Рендер **только после approve** текущей версии сценария — проверка в `pipeline/orchestrator.py`, не только в UI.
- Публикация только после финального одобрения Босса; дневные лимиты канала соблюдаются в scheduler.
- ClipFactory живёт в `bossfight33r/100`; здесь его аналоги — `src/techstudio/core/` (ADR 0001). Не ломать.
- Production-промпты (`src/techstudio/prompts/`) автоматически не меняются; предложения — в файлы для ручного ревью.

Облачные сессии: `.claude/hooks/session-start.sh` ставит venv и зависимости автоматически.

Команды: `make setup`, `make test`, `make lint`, `.venv/bin/studio --help`, `.venv/bin/studio doctor`.
