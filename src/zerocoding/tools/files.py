
from pathlib import Path


def read_text(path):
    return Path(path).read_text(encoding="utf-8")


def write_text(path, content):
    Path(path).write_text(content, encoding="utf-8")
