"""Политика команд терминальных сцен. Нарушение (severity=error) блокирует рендер и видно на ревью.

Денилист, а не песочница: песочница (Docker) — второй рубеж. Здесь ловим то, что нельзя ни
выполнять, ни показывать зрителю как пример.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

Severity = Literal["error", "warning"]


@dataclass(frozen=True)
class Rule:
    id: str
    pattern: re.Pattern
    message: str
    severity: Severity = "error"


def _r(rule_id: str, regex: str, message: str, severity: Severity = "error") -> Rule:
    return Rule(rule_id, re.compile(regex, re.I), message, severity)


_SEP = r"(?:^|[;&|(`]|\$\(|&&|\|\|)\s*"  # начало команды
_RM_ROOT_TARGET = r"(?:/|/\*|~/?|~/\*|\$HOME/?|\$\{HOME\}/?|\.\./?|/[a-z]+/?)(?:\s|$|;|&|\|)"

RULES: tuple[Rule, ...] = (
    _r(
        "rm-root",
        _SEP
        + r"rm\s+(?:-[a-z]*\s+|--[a-z-]+\s+)*-[a-z]*[rR][a-z]*\s+(?:-[a-z]*\s+|--[a-z-]+\s+)*"
        + _RM_ROOT_TARGET,
        "рекурсивное удаление корня, домашней или системной папки",
    ),
    _r("rm-no-preserve-root", r"--no-preserve-root", "rm --no-preserve-root"),
    _r("mkfs", _SEP + r"mkfs(?:\.\w+)?\b", "форматирование файловой системы (mkfs)"),
    _r(
        "dd-device",
        r"\bdd\b[^\n]*\bof=/dev/(?!null\b|zero\b|stdout\b|stderr\b)",
        "dd на устройство",
    ),
    _r(
        "write-block-device",
        r">\s*/dev/(?:sd[a-z]|hd[a-z]|vd[a-z]|xvd[a-z]|nvme\d|mmcblk\d|disk\d|mtd\d|mtdblock\d)",
        "запись в блочное устройство",
    ),
    _r(
        "wipefs",
        _SEP + r"(?:wipefs|shred|blkdiscard|fdisk|sfdisk|parted|mtd\s+erase)\b",
        "затирание/разметка диска",
    ),
    _r("fork-bomb", r":\s*\(\s*\)\s*\{[^}]*:\s*\|\s*:", "fork bomb"),
    _r("fork-bomb-generic", r"\b(\w+)\s*\(\s*\)\s*\{[^}]*\b\1\s*\|\s*\1\s*&", "fork bomb"),
    _r(
        "power",
        _SEP
        + r"(?:shutdown|reboot|halt|poweroff|init\s+[06]|systemctl\s+(?:poweroff|reboot|halt|kexec))\b",
        "выключение или перезагрузка",
    ),
    _r(
        "pipe-to-shell",
        r"\b(?:curl|wget|fetch)\b[^|\n]*\|\s*(?:sudo\s+)?(?:ba|z|da|k)?sh\b"
        r"|\b(?:curl|wget)\b[^|\n]*\|\s*(?:sudo\s+)?python\d?\b",
        "pipe из сети в shell",
    ),
    _r(
        "shell-from-net",
        r"(?:ba|z)?sh\s+(?:-c\s+)?[\"']?\$\((?:curl|wget)\b|<\(\s*(?:curl|wget)\b",
        "выполнение скрипта из сети",
    ),
    _r(
        "sudo",
        _SEP + r"(?:sudo|doas|pkexec)\b|\bsu\s+-|\bsu\s+root\b",
        "повышение привилегий (sudo/su)",
    ),
    _r(
        "chmod-root",
        r"\bch(?:mod|own)\s+(?:-[a-z]*R[a-z]*\s+)\S+\s+/(?:\s|$)",
        "рекурсивная смена прав на /",
    ),
    _r(
        "chmod-777-root",
        r"\bchmod\s+(?:-R\s+)?777\s+/(?:\s|$|etc|usr|bin)",
        "chmod 777 на системные пути",
    ),
    _r("kill-all", _SEP + r"kill\s+-9\s+-1\b|\bkillall5\b", "убийство всех процессов"),
    _r("history-wipe", r"\bhistory\s+-c\b|>\s*~/.bash_history", "затирание истории", "warning"),
    _r("crypto-miner", r"\b(?:xmrig|minerd|cpuminer)\b", "майнер"),
    _r("reverse-shell", r"/dev/tcp/|\bnc\b[^\n]*\s-e\s|\bncat\b[^\n]*--exec", "reverse shell"),
    # обфускация: то, что policy не может прочитать, не выполняем и не показываем
    _r("eval", _SEP + r"eval\b", "eval — команда не читается policy"),
    _r(
        "decode-to-shell",
        r"\b(?:base64\s+(?:-d|--decode|-D)|xxd\s+-r|openssl\s+(?:base64|enc)\s+[^|]*-d)[^|]*\|\s*(?:sudo\s+)?(?:ba|z|da|k)?sh\b",
        "декодирование в shell — команда не читается policy",
    ),
    _r(
        "subst-decode",
        r"\$\([^)]*\b(?:base64\s+(?:-d|--decode|-D)|xxd\s+-r)\b",
        "выполнение декодированного текста — команда не читается policy",
    ),
    _r(
        "iptables-flush",
        _SEP + r"(?:iptables|nft)\s+(?:-F|flush\s+ruleset)\b",
        "сброс фаервола",
        "warning",
    ),
)

# Секреты: реальные ключи и пароли в командах запрещены — только плейсхолдеры <YOUR_KEY>
SECRET_RULES: tuple[Rule, ...] = (
    _r("secret-anthropic", r"\bsk-ant-[A-Za-z0-9_-]{10,}", "похоже на ключ Anthropic"),
    _r("secret-openai", r"\bsk-[A-Za-z0-9]{20,}", "похоже на API-ключ"),
    _r("secret-github", r"\bgh[pousr]_[A-Za-z0-9]{20,}", "похоже на токен GitHub"),
    _r("secret-aws", r"\bAKIA[0-9A-Z]{16}\b", "похоже на ключ AWS"),
    _r("secret-slack", r"\bxox[abprs]-[A-Za-z0-9-]{10,}", "похоже на токен Slack"),
    _r("secret-telegram", r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b", "похоже на токен Telegram-бота"),
    _r("secret-private-key", r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "приватный ключ"),
    _r(
        "secret-assignment",
        r"(?<![a-z0-9])(?:password|passwd|pass|token|secret|api[_-]?key|apikey)\s*[=:]\s*(?![\"']?<[A-Z0-9_]+>)[\"']?[^\s\"'<>$]{4,}",
        "пароль/токен в команде — замени на <YOUR_KEY>",
    ),
    _r(
        "secret-header",
        r"authorization:\s*(?:bearer|token|basic)\s+(?!<[A-Z0-9_]+>)[A-Za-z0-9._~+/=-]{8,}",
        "токен в заголовке — замени на <YOUR_TOKEN>",
    ),
    _r(
        "secret-sshpass",
        r"\bsshpass\s+-p\s*(?!<[A-Z0-9_]+>)\S+",
        "пароль в sshpass — замени на <YOUR_PASSWORD>",
    ),
    _r(
        "secret-url-creds",
        r"\b[a-z][a-z0-9+.-]*://[^\s/:@]+:(?!<[A-Z0-9_]+>@)[^\s/@]+@",
        "логин:пароль в URL — замени на <YOUR_PASSWORD>",
    ),
)

NETWORK_TOOLS = re.compile(
    _SEP
    + r"(?:curl|wget|ping|ping6|traceroute|tracepath|mtr|dig|nslookup|host|whois|ssh|scp|sftp|rsync|"
    r"nc|ncat|telnet|ftp|apt(?:-get)?\s+(?:install|update|upgrade)|pip3?\s+install|"
    r"npm\s+(?:install|i)\b|git\s+(?:clone|pull|fetch|push)|opkg\s+(?:update|install)|docker\s+pull)\b",
    re.I,
)


# сетевые вызовы в коде файлов (python/sh), исполняемых в live-сцене
NETWORK_CODE = re.compile(
    r"\b(?:requests\.(?:get|post|put|delete|head)|urllib\.request|urlopen|httpx\.|aiohttp|socket\.create_connection|"
    r"subprocess\.\w+\(\s*\[\s*[\"'](?:curl|wget|ping|dig|nslookup|ssh)[\"'])",
)


@dataclass(frozen=True)
class Violation:
    scene_id: str
    command: str
    rule: str
    message: str
    severity: Severity

    def __str__(self) -> str:
        return f"[{self.severity}] {self.scene_id}: {self.message}: `{self.command}`"


def check_command(
    command: str, *, scene_id: str = "-", network: bool = False, mode: str = "live"
) -> list[Violation]:
    out: list[Violation] = []
    for rule in (*RULES, *SECRET_RULES):
        if rule.pattern.search(command):
            out.append(Violation(scene_id, command, rule.id, rule.message, rule.severity))
    if mode == "live" and not network and NETWORK_TOOLS.search(command):
        out.append(
            Violation(
                scene_id,
                command,
                "needs-network",
                "команде нужна сеть: поставь network: true (будет видно на ревью) или mode: replay",
                "error",
            )
        )
    return out


def check_scene(scene) -> list[Violation]:
    if getattr(scene, "type", None) != "terminal":
        return []
    out: list[Violation] = []
    for cmd in scene.commands:
        out.extend(check_command(cmd, scene_id=scene.id, network=scene.network, mode=scene.mode))
    return out


def check_script(script) -> list[Violation]:
    out: list[Violation] = []
    for scene in script.scenes:
        out.extend(check_scene(scene))
        if getattr(scene, "type", None) == "code":
            # код тоже показывается зрителю: секреты в нём запрещены
            for rule in SECRET_RULES:
                if rule.pattern.search(scene.code):
                    out.append(Violation(scene.id, "<code>", rule.id, rule.message, rule.severity))
        # код из files выполняется в песочнице — те же запреты, что и для команд
        for name, src in getattr(scene, "files", {}).items():
            code = script.scene(src).code
            for line in code.splitlines():
                # os.system("rm -rf /") / run(["rm", "-rf", "/"]) → ;rm -rf /;
                as_cmd = re.sub(r"[\"']\s*,\s*[\"']", " ", line)
                as_cmd = re.sub(r"[\"'\[\]]", ";", as_cmd)
                for rule in RULES:
                    if rule.pattern.search(as_cmd):
                        out.append(
                            Violation(
                                scene.id,
                                f"{name}: {line.strip()[:80]}",
                                rule.id,
                                rule.message,
                                rule.severity,
                            )
                        )
                if not scene.network and NETWORK_CODE.search(line):
                    out.append(
                        Violation(
                            scene.id,
                            f"{name}: {line.strip()[:80]}",
                            "needs-network",
                            "код ходит в сеть: нужен network: true",
                            "error",
                        )
                    )
    return out


def errors(violations: list[Violation]) -> list[Violation]:
    return [v for v in violations if v.severity == "error"]
