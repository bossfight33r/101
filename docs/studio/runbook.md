# Runbook TechStudio

## Установка (Мак)
```bash
make setup-mac                      # uv venv + deps (+faster-whisper, mlx)
cp .env.example .env                # ANTHROPIC_API_KEY, TELEGRAM_BOT_TOKEN, TS_ADMIN_IDS
cp config/studio/channel.example.yaml config/studio/channel.yaml   # шрифт: /System/Library/Fonts/Supplemental/Arial.ttf
make sandbox-image                  # docker build -t techstudio-sandbox:latest docker/studio
docker pull minlag/mermaid-cli:latest
.venv/bin/studio doctor
TS_TTS=piper TS_TRANSCRIBER=faster_whisper make selftest   # демо-видео на реальных компонентах
```

## Piper
```bash
uv pip install --python .venv/bin/python piper-tts
.venv/bin/python -m piper.download_voices --download-dir data/studio/voices ru_RU-dmitri-medium ru_RU-irina-medium
# или вручную: https://huggingface.co/rhasspy/piper-voices/tree/main/ru/ru_RU  (.onnx + .onnx.json рядом)
```
Произношение терминов — `config/studio/voices.yaml` → `pronunciation` (только для TTS).

## YouTube
1. Google Cloud Console → проект → включить YouTube Data API v3 и YouTube Analytics API.
2. OAuth consent (External, test users — свой аккаунт), Credentials → OAuth client ID → Desktop app.
3. JSON → `data/studio/secrets/youtube_client_secret.json`.
4. `.venv/bin/studio auth youtube --account yt_main` (браузер) → `data/studio/secrets/yt_main.json`.
Миниатюры через API требуют подтверждённого канала; иначе файл в `data/studio/exports/{id}/`.

## Проверки без Docker
- `brew install vhs` → `TS_VHS_BIN=vhs`: каждая tape проходит `vhs validate` до запуска песочницы.
- mermaid-cli локально: `npm i -g @mermaid-js/mermaid-cli` → `TS_MERMAID_BIN=mmdc`. Под root (Linux-сервер)
  нужен `TS_MERMAID_PUPPETEER_CONFIG=puppeteer.json` с `{"executablePath": "…/chrome", "args": ["--no-sandbox"]}`.

## Сеть песочницы (`network: true`)
По умолчанию у песочницы сети нет (`--network none`). Сцена с `network: true` получает
`TS_SANDBOX_NETWORK` (по умолчанию `bridge`) — а bridge видит и домашнюю сеть (роутер, NAS).
Linux-хост — сеть только в интернет:
```bash
docker network create -o com.docker.network.bridge.name=ts-inet ts-internet-only
for net in 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16 169.254.0.0/16; do
  sudo iptables -I DOCKER-USER -i ts-inet -d $net -j DROP
done
echo TS_SANDBOX_NETWORK=ts-internet-only >> .env
```
Мак (Docker Desktop): фильтровать LAN из VM сложно — для всего, что касается роутера и локальной
сети, используй `mode: replay`, а `network: true` — только для публичного интернета (curl, dig, pip).

## Уведомления
`studio script new <topic> --notify`, `studio render <id> --notify`, `studio notify <id>` — гейт в Telegram всем `TS_ADMIN_IDS`.

## Replay-вывод с устройств
Для `mode: replay` положи реальный вывод команды с роутера:
`data/studio/assets/replay/<topic>/<scene>/0.txt` (1.txt … для следующих команд сцены) или один файл `<key>.txt`.
Пример: `ssh root@192.168.1.1 'opkg update' > data/studio/assets/replay/openwrt-first-steps/opkg-update/0.txt`.

## Ежедневно
```bash
studio topic list
studio script new <topic>           # или /new <topic> в боте
studio script export <id> -o /tmp/s.yaml && $EDITOR /tmp/s.yaml && studio script import <id> /tmp/s.yaml
studio script approve <id>          # или ✅ в боте → рендер стартует сам
studio render <id>                  # CLI-путь
studio review <id> approve --thumb B && studio publish <id>
studio track && studio report --recommendations
studio topic suggest && studio topic accept <file> <id>
```

## Диск
`studio cleanup` — сколько места займут промежуточные файлы вышедших видео; `studio cleanup --apply` — удалить.
Остаются long.mp4, шортсы, миниатюры, SRT, сценарии, озвучка. Перерендер такого видео пересоберёт удалённое.

## Сбои
- `studio status <id>` — этап и ошибка. `studio retry <id>` — повтор из кеша.
- Policy заблокировала команду — правь сценарий (import), не обходи policy.
- Песочница: таймаут → `TS_SANDBOX_TIMEOUT`; нужна сеть → `network: true` в сцене (видно на ревью).
- Зависший контейнер: `docker ps --filter name=ts-` → `docker kill`.
