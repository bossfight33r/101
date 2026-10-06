# TechStudio

Конвейер обучающих tech-видео без лица (роутеры, прошивки, сети, Linux, Python-автоматизация):
тема → сценарий → ревью Босса → визуалы (терминал, код, схемы, слайды, скриншоты) → озвучка →
длинное видео 16:9 + шортсы 9:16 → ревью → публикация на YouTube → аналитика.

```bash
make setup
.venv/bin/studio doctor
.venv/bin/studio topic import config/studio/topics.example.yaml
.venv/bin/studio script new openwrt-first-steps   # → script_review
.venv/bin/studio script approve <VIDEO_ID>       # рендер возможен только после approve
.venv/bin/studio render <VIDEO_ID>               # озвучка → визуалы → long.mp4 + шортсы
.venv/bin/studio review <VIDEO_ID> approve --thumb B && .venv/bin/studio publish <VIDEO_ID>
.venv/bin/studio bot                             # то же через Telegram (только TS_ADMIN_IDS)
.venv/bin/studio selftest                        # демо-видео на реальных Docker/VHS/mermaid/Piper/ASR
```

Без ключей и Docker всё работает на фейках: `TS_LLM_PROVIDER=fake TS_TTS=fake TS_TRANSCRIBER=fake TS_RENDERERS=auto TS_PUBLISHER=fake`.

Принципы: каждый сценарий проходит ревью Босса до рендера; терминальные сцены — реальный вывод
реальных команд (Docker-песочница или replay с устройства); дневные лимиты канала; без финального
одобрения ничего не публикуется.

Точка входа для новой сессии — [`docs/studio/STATUS.md`](docs/studio/STATUS.md).
Документация: [architecture](docs/studio/architecture.md), [pipeline](docs/studio/pipeline.md),
[формат сценария](docs/studio/script-format.md), [runbook](docs/studio/runbook.md).
