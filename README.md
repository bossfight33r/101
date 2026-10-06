# TechStudio

Конвейер обучающих tech-видео без лица (роутеры, прошивки, сети, Linux, Python-автоматизация):
тема → сценарий → ревью Босса → визуалы (терминал, код, схемы, слайды, скриншоты) → озвучка →
длинное видео 16:9 + шортсы 9:16 → ревью → публикация на YouTube → аналитика.

```bash
make setup
.venv/bin/studio doctor
.venv/bin/studio topic import config/studio/topics.example.yaml
.venv/bin/studio script new openwrt-first-steps
```

Точка входа для новой сессии — [`docs/studio/STATUS.md`](docs/studio/STATUS.md).
Документация: [architecture](docs/studio/architecture.md), [pipeline](docs/studio/pipeline.md),
[формат сценария](docs/studio/script-format.md), [runbook](docs/studio/runbook.md).
