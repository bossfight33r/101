# ADR 0003 — Policy команд и фиксация одобрения

**Policy.** `sandbox/policy.py` — денилист регулярками (удаление корня/системных папок, mkfs, dd и
запись в блочные устройства, wipefs/shred, fork bomb, shutdown/reboot, pipe из сети в shell, sudo/su,
reverse shell, майнеры) + правила секретов (ключи Anthropic/GitHub/AWS/Slack/Telegram, приватные ключи,
`password=…`, токены в заголовках и URL). Разрешены только плейсхолдеры `<YOUR_KEY>`.
Для `mode: live` без `network: true` сетевые утилиты (curl, ping, dig, ssh, git clone, pip install…)
— ошибка: иначе в видео попадёт вывод «нет сети». Policy проверяется при генерации, импорте, approve и
повторно в orchestrator перед рендером. Песочница Docker — второй рубеж, не замена.

**Одобрение.** `approve` пишет `videos/{id}/approved.json` с версией и sha256 канонического JSON
сценария. Orchestrator сверяет: `approved_version == script_version`, хеш совпадает, валидация зелёная.
Правка `script.yaml` мимо `import` блокирует рендер. Любой import/regen снимает approve.
