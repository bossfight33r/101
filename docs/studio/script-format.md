# Формат сценария TechStudio

Этот файл читает и Босс, и LLM при генерации сценария. Сценарий — YAML (`script.yaml`),
валидируется `techstudio.schemas.Script`. Неизвестные поля запрещены.

## Верхний уровень

```yaml
video_id: v20261006-openwrt-first-steps   # не менять
topic_id: openwrt-first-steps             # не менять
version: 1                                # растёт при каждом импорте правки
title: "OpenWrt: первые 10 минут после прошивки"
hook: "Через восемь минут у тебя будет роутер с паролем, свежими пакетами и веб-панелью на русском."
outro: "Ставь лайк, если пригодилось. В следующем видео — VPN на роутере."
scenes: [...]
```

- `hook` — звучит первым (служебная сцена `hook`), не дольше 10 секунд: что зритель сможет сделать после видео.
- `outro` — короткая концовка (служебная сцена `outro`), не короче `outro_min_sec` канала (10 с) — место под конечную заставку YouTube. Пустое — предупреждение на ревью.
- Длина всего ролика — `longform.min_sec`..`longform.max_sec` канала (по умолчанию 6–12 мин) при
  `words_per_minute` (по умолчанию 140).

## Поля любой сцены

| поле | тип | смысл |
|---|---|---|
| `id` | `[a-z0-9_-]`, ≤32 | уникален; `hook`/`outro` заняты |
| `type` | terminal / code / diagram / slide / image | тип визуала |
| `narration` | текст | что говорит голос. Одна идея на сцену. Короткие фразы. |
| `min_sec` | число | минимум длительности сцены (визуалу нужно время) |
| `chapter` | текст или нет | начинает главу YouTube с этим заголовком |
| `short_candidate` | bool | сцена годится в шортс (3–5 на видео) |
| `short_hook` | текст | первая фраза шортса (озвучивается отдельно, если включено в канале) |

Длительность сцены = max(озвучка + паузы, `min_sec`, минимум визуала). Озвучка никогда не режется.

## terminal — реальные команды в песочнице

```yaml
- id: ss-basic
  type: terminal
  chapter: "Кто слушает порты"
  narration: "Смотрим, какие порты открыты. Ключи t и u — это TCP и UDP, l — только слушающие, n — без резолва имён."
  mode: live            # live — выполняется в Docker-песочнице; replay — вывод из файла
  commands:
    - ss -tuln
  network: false        # true — песочнице дадут сеть. Видно на ревью.
  typing_speed: 45      # мс на символ
  min_sec: 8
  short_candidate: true
  short_hook: "Одна команда покажет все открытые порты."
```

Код, показанный в code-сцене, можно запустить в live-сцене: `files` кладёт его в `~` контейнера
до первой команды (невидимо для зрителя). Ключ — имя файла, значение — `id` code-сцены:

```yaml
- id: sweep-run
  type: terminal
  chapter: "Запускаем"
  files:
    sweep.py: sweep-code      # код из сцены sweep-code выше
  commands:
    - python3 sweep.py 127.0.0.1
  narration: "Запускаем скрипт на своей машине. Видишь — локальный хост жив."
```

Код из `files` проходит ту же policy, что и команды (удаление корня, sudo, сеть без `network: true`).
Live-команды стартуют в пустом `~` контейнера: всё, что им нужно, создаётся в сцене или через `files`.

`mode: replay` — для роутеров и реальных устройств. Команда набирается в VHS, а вывод берётся из файла
с **реальным** выводом с устройства (`data/studio/<replay_output_key>/<N>.txt`, N — номер команды с 0,
или один файл, если команда одна):

```yaml
- id: opkg-update
  type: terminal
  mode: replay
  replay_output_key: assets/replay/openwrt-first-steps/opkg-update
  commands:
    - opkg update
  narration: "Обновляем список пакетов. Роутеру нужен интернет, иначе тут будут ошибки."
```

Правила команд: только реалистичные и безопасные; без sudo, без `curl | sh`, без удаления корня,
mkfs, dd на диски, reboot/shutdown, fork bomb. Ключи и пароли — только плейсхолдеры `<YOUR_KEY>`.
Нарушение блокирует рендер и показывается на ревью.

## code — код с подсветкой

```yaml
- id: sweep-code
  type: code
  chapter: "Скрипт пинга"
  language: python
  reveal: by_line        # all — сразу весь код; by_line — построчно
  highlight_lines: [5, 6]
  code: |
    import subprocess
    from concurrent.futures import ThreadPoolExecutor

    def alive(host):
        r = subprocess.run(["ping", "-c1", "-W1", host], capture_output=True)
        return host, r.returncode == 0
  narration: "Функция alive пингует один хост и возвращает, ответил ли он."
  min_sec: 10
```

Код ≤ ~25 строк на сцену; длинные строки в 9:16 переносятся.

## diagram — схема Mermaid

```yaml
- id: nat-diagram
  type: diagram
  chapter: "Как ходит трафик"
  mermaid: |
    flowchart LR
      PC[Ноутбук] -->|192.168.1.10| R[Роутер OpenWrt]
      R -->|NAT| ISP[Провайдер]
      ISP --> NET((Интернет))
  narration: "Ноутбук ходит в интернет через роутер, а роутер подменяет адрес — это NAT."
```

Если схема не рендерится, вместо неё будет fallback-слайд, и это видно на финальном ревью.

## slide — тезисы

```yaml
- id: plan
  type: slide
  title: "Что сделаем"
  bullets:               # не больше 4
    - "Зайдём по SSH"
    - "Сменим пароль"
    - "Поставим LuCI"
  narration: "План простой: заходим, меняем пароль, ставим веб-панель."
```

## image — мой скриншот или фото

```yaml
- id: luci-screen
  type: image
  asset_key: assets/openwrt-first-steps/luci.png   # путь в data/studio/
  caption: "LuCI после установки"
  narration: "Так выглядит панель после установки русского пакета."
```

## Стиль речи

- Живая разговорная русская речь, короткие фразы, «ты».
- Запрещено: «в этом видео мы рассмотрим», «давайте разберёмся», «итак», вода и повторы.
- Одна идея на сцену. Термины на английском пишем как есть (OpenWrt, SSH) — произношение задаёт `voices.yaml`.
