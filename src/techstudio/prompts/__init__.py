from importlib.resources import files


def load(name: str) -> str:
    return (files(__package__) / name).read_text(encoding="utf-8")
