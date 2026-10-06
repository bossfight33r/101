"""YAML round-trip сценария для ручной правки Боссом."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from techstudio.schemas import Script

_SCENE_KEY_ORDER = ("id", "type", "chapter", "mode", "network", "narration")


class ScriptParseError(ValueError):
    pass


class _Dumper(yaml.SafeDumper):
    pass


def _str_presenter(dumper, data: str):
    style = "|" if "\n" in data else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


_Dumper.add_representer(str, _str_presenter)


def _ordered_scene(scene: dict) -> dict:
    out = {k: scene[k] for k in _SCENE_KEY_ORDER if k in scene}
    out.update({k: v for k, v in scene.items() if k not in out})
    return out


def to_yaml(script: Script, header: str = "") -> str:
    data = script.model_dump(mode="json", exclude_none=True)
    data["scenes"] = [_ordered_scene(s) for s in data["scenes"]]
    body = yaml.dump(data, Dumper=_Dumper, allow_unicode=True, sort_keys=False, width=100)
    if header:
        body = "".join(f"# {line}\n" if line else "#\n" for line in header.splitlines()) + body
    return body


def from_yaml(text: str) -> Script:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise ScriptParseError(f"YAML не читается: {e}") from e
    if not isinstance(data, dict):
        raise ScriptParseError("ожидался YAML-словарь сценария")
    try:
        return Script.model_validate(data)
    except ValidationError as e:
        raise ScriptParseError(format_validation_error(e)) from e


def format_validation_error(e: ValidationError) -> str:
    lines = []
    for err in e.errors():
        loc = ".".join(str(p) for p in err["loc"])
        lines.append(f"- {loc}: {err['msg']}")
    return "Сценарий невалиден:\n" + "\n".join(lines)


def save(script: Script, path: Path, header: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(to_yaml(script, header), encoding="utf-8")
    tmp.replace(path)
    return path


def load(path: Path) -> Script:
    return from_yaml(path.read_text(encoding="utf-8"))
