# STATUS — TechStudio

Новая сессия: прочитай `CLAUDE.md` и этот файл, затем «Следующий шаг».

Ветка: `claude/beautiful-pasteur-auu6yr` (репо `bossfight33r/101`). TechStudio строится с нуля,
без кода ClipFactory (ADR 0001). `make lint` и `make test` зелёные (без сети, Docker и реальных API).

| Фаза | Статус |
|---|---|
| 0 Foundation | ✅ |
| 1 Сценарий | ✅ |
| 2 Визуалы | ✅ terminal и mermaid проверены через фейки — реальный прогон на Маке |
| 3 Озвучка и сборка | ✅ Piper и ASR — через фейки, реальный прогон на Маке |
| 4 Ревью и публикация | ✅ Telegram/YouTube — фейки, реальный прогон на Маке |
| 5 Аналитика и темы | ✅ |

## Готово
- CLI `studio`: `doctor`, `topic add|list|import|suggest|accept`, `script new|export|import|approve|regen`,
  `videos`, `render [--scene] [--notify]`, `status`, `selftest`, `cleanup [--apply]`, `backup`, `retry`, `review approve|reject|thumb`, `publish`, `notify`,
  `auth youtube`, `bot`, `track`, `report [--recommendations]`.
- Сценарий: LLM → Pydantic, валидация (хук ≤ 10 с, длительность, запрещённые фразы, шортсы, mermaid реальным mmdc если есть, policy), YAML round-trip, версии, approve с хешем.
- Policy песочницы (денилист + секреты + сеть только по флагу; код из `files` проверяется тем же денилистом), Docker-раннер (non-root, без сети, read-only, cap-drop, лимиты, таймаут).
- Рендереры всех типов в 16:9 и 9:16 нативно; replay через DEBUG trap; `files` — код из code-сцены в `~` песочницы; fallback-слайды с предупреждением.
- Озвучка, ASR-тайминги, выравнивание к исходному тексту; длинное видео с главами, SRT, музыкой (ducking) и loudnorm −14 LUFS; шортсы с ASS-субтитрами на плашке; 3 миниатюры; превью.
- Манифесты и resume: retry не переделывает озвучку и визуалы. Блокировка: один рендер/публикация на видео.
- Бот: гейт 1 и гейт 2, `/regen VID SCENE пожелание`, только `TS_ADMIN_IDS`, HTML экранируется, длинные сообщения режутся по строкам, прогресс рендера в одном сообщении; `notify` из CLI.
- Публикация: главы, SRT, миниатюра (экспорт при ошибке), шортсы после длинного, дневные лимиты, перепланирование просроченных слотов при повторе. Видео с fake-визуалами одобрить нельзя.
- Аналитика: снимки, отчёт по темам/типам сцен/хукам, файл рекомендаций, предложения тем с ручным accept.
- Безопасность: policy ловит обфускацию (eval, `base64 -d | sh`, `| sh`, команды из переменных, строки в `python -c`/`sh -c`), ключи ассетов только `assets/…`, сеть песочницы настраивается (`TS_SANDBOX_NETWORK`, рецепт без LAN).
- Под YouTube: аутро ≥ 10 с под конечную заставку, хэштеги, обещание хука на слайде; предупреждения на ревью — длительность вне окна, сцены > 45 с без смены визуала, длинный заголовок.
- Скорость: параллельный рендер сцен (`TS_RENDER_WORKERS`), очистка промежуточных кадров.
- Тесты: 234 passed, 9 skipped (skip — тесты на реальных vhs/mmdc, включаются `TS_VHS_BIN`, `TS_MERMAID_BIN`).

### Проверено по-настоящему в этом окружении
- ffmpeg: длинное 1920x1080 + шортсы 1080x1920 + ASS, громкость −14.0 LUFS (ebur128), fade, музыка с ducking.
- Рендеры code/slide/image/fallback; кадры просмотрены, кириллица ок.
- mermaid-cli 12 (npm + локальный Chromium): рендер схем в обеих ориентациях, проверка синтаксиса — нашёл и исправил несовместимые флаги `-w/-H`.
- `vhs validate` (VHS собран из исходников): все варианты tape валидны — нашёл и исправил `Output` без кавычек.
- replay-трюк (extdebug + DEBUG trap) в интерактивном bash.
- piper-tts 1.8: наши флаги принимаются CLI; faster-whisper 1.2: сигнатуры совпадают.
- YouTube Data/Analytics: тела запросов через статическую discovery + HttpMock; Anthropic SDK: параметры `beta.messages.stream` сверены с сигнатурой.

## Не готово / ограничения
- Docker-песочница, VHS-рендер, голос Piper и модель whisper здесь не запускались: запуск dockerd и скачивание ttyd запрещены политикой окружения, HuggingFace закрыт сетью. Всё — в «Проверить на Маке».
- `TS_RENDERERS=auto` без Docker даёт fake-терминал; такое видео дойдёт до ревью, но финальный approve заблокирован. Для продакшена — `TS_RENDERERS=real`.
- Очередь inline (без Redis): рендер в процессе CLI/бота.
- Бот отправляет файлы ≤ 50 МБ (лимит Bot API) — длинное видео идёт как превью 360p.
- mlx-whisper-бэкенд написан по документации, не запускался.

## Блокеры
Нет. xfail-тестов нет.

## Проверить на Маке
```bash
make setup-mac && cp .env.example .env            # ключи — только в .env
cp config/studio/channel.example.yaml config/studio/channel.yaml
#   style.font/font_bold: /System/Library/Fonts/Supplemental/Arial.ttf (+ Arial Bold.ttf), mono: /System/Library/Fonts/Menlo.ttc
make sandbox-image && docker pull minlag/mermaid-cli:latest
# Piper + голос: docs/studio/runbook.md#piper
.venv/bin/studio doctor                            # всё обязательное — ✅
make test

# 0. Всё разом: doctor --strict + демо-видео на реальных Docker/VHS/mermaid/Piper/ASR (без LLM и публикации)
TS_TTS=piper TS_TRANSCRIBER=faster_whisper make selftest
open data/studio-selftest/videos/*/long.mp4
#   каждый ❌ — с этапом и причиной; ниже — те же проверки по отдельности

# 1. Песочница и VHS (реальный вывод)
.venv/bin/studio topic import config/studio/topics.example.yaml
.venv/bin/studio script new linux-ss-vs-netstat
.venv/bin/studio script approve <ID>
TS_RENDERERS=real .venv/bin/studio render <ID>
open data/studio/videos/<ID>/scenes/*/visual_16x9.mp4
#   проверить: терминал показывает настоящий вывод ss; VHS под uid 1000 с --read-only стартует
#   (если Chromium падает — TS_SANDBOX_READ_ONLY=false, остальная изоляция остаётся), 9:16 читаем
#   сцена с files (тема python-ping-sweep): python3 sweep.py реально выполняется в контейнере

# 2. Сеть выключена
docker run --rm --network none techstudio-sandbox:latest --help >/dev/null; echo ok
#   сцена с `curl` без network: true должна быть отклонена validate/policy

# 3. Replay (OpenWrt)
ssh root@192.168.1.1 'opkg update' > data/studio/assets/replay/openwrt-first-steps/cmd2/0.txt
#   сцена mode: replay — вывод из файла, команда не выполняется

# 4. Mermaid реально + fallback: в scenes/<diagram>/ нет предупреждения fallback

# 5. Piper + faster-whisper/mlx: TS_TTS=piper TS_TRANSCRIBER=faster_whisper (или mlx)
#   проверить: произношение OpenWrt/SSH, субтитры в исходном написании, синхрон слов в шортсах

# 6. Claude: TS_LLM_PROVIDER=anthropic, studio script new <topic> — качество сценария, 6–12 мин

# 7. Бот: TELEGRAM_BOT_TOKEN, TS_ADMIN_IDS; .venv/bin/studio bot
#   /new <topic> → гейт 1 → правка YAML файлом → ✅ → рендер → гейт 2 → миниатюра → ✅ → публикация;
#   с чужого аккаунта бот молчит

# 8. YouTube (тестовый канал): studio auth youtube --account yt_main
#   studio publish <ID> → в Studio: private + запланировано, главы в описании, субтитры, миниатюра
#   studio track (после publishAt) && studio report --recommendations
```

## Следующий шаг
Пройти «Проверить на Маке» по порядку и исправить найденное на реальных бэкендах: в первую очередь
запуск VHS в песочнице с `--read-only`/non-root, размер шрифтов терминала в 9:16, качество сценариев
на реальном Claude (промпт `prompts/script.md`), тайминг субтитров на реальном ASR.
