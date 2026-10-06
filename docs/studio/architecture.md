# Архитектура TechStudio

```mermaid
flowchart LR
  T[Topic<br/>бэклог] --> G[script/generate<br/>LLM]
  G --> V{validate<br/>+ policy}
  V --> R1[[Гейт 1: ревью сценария<br/>бот / CLI]]
  R1 -- правка YAML --> V
  R1 -- approve + hash --> O[pipeline/orchestrator<br/>проверка approve]
  O --> VO[voice: Piper → loudnorm → ASR-тайминги]
  VO --> VI[render: terminal / code / diagram / slide / image]
  VI -- terminal --> SB[(Docker-песочница<br/>VHS, без сети)]
  VI --> AS[assemble: сегменты → long 16:9 + SRT + главы<br/>shorts 9:16 + ASS]
  AS --> TH[metadata + 3 миниатюры + превью]
  TH --> R2[[Гейт 2: финальное ревью]]
  R2 -- approve + миниатюра --> P[publish: YouTube<br/>scheduler + лимиты]
  P --> TR[track: статистика]
  TR --> REP[report + рекомендации<br/>+ предложения тем]
  REP -. ручной accept .-> T
```

## Модули (`src/techstudio/`)

| модуль | роль |
|---|---|
| `schemas.py` | все контракты: Channel, Topic, Script/сцены, артефакты этапов, статусы, Publication, StatsSnapshot |
| `config.py` | Settings (env `TS_*`), YAML канала/тем/голосов |
| `core/` | ffmpeg-обёртка, probe, энкодеры, storage, манифесты, лог, SQLite, LLM/ASR-бэкенды, субтитры (аналоги ClipFactory, ADR 0001) |
| `script/` | генерация, валидация, YAML round-trip, fake-LLM |
| `sandbox/` | policy команд, Docker-раннер |
| `render/` | рендереры сцен и registry (`TS_RENDERERS`) |
| `voice/` | TTSProvider: Piper, Fake; словарь произношения |
| `timing.py` | длительность сцен, выравнивание слов, freeze/trim |
| `assemble/` | сегменты, длинное видео, шортсы, главы, музыка |
| `thumbnail/` | 3 варианта миниатюр |
| `pipeline/` | жизненный цикл сценария, этапы, orchestrator, ревью, публикация |
| `publish/` | YouTube API, fake, scheduler |
| `track/` | сбор статистики, отчёт |
| `topics/` | бэклог, предложения тем |
| `bot/` | логика гейтов + aiogram-адаптер |

## Инварианты
- Рендер только для одобренной версии (`approved.json` = версия + sha256), проверка в orchestrator.
- Команды — только через policy и только в песочнице; сеть — только с явным `network: true`.
- Публикация только после финального approve и выбора миниатюры; дневные лимиты в scheduler.
- Субтитры — исходный текст сценария; словарь произношения только для TTS.
