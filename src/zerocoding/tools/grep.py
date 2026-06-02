
import re
from pathlib import Path


def search(pattern, directory):
    regex = re.compile(pattern)
    results = []
    for path in Path(directory).rglob("*"):
        if path.is_file():
            text = path.read_text(encoding="utf-8", errors="ignore")
            for lineno, line in enumerate(text.splitlines(), start=1):
                if regex.search(line):
                    results.append((path, lineno, line.strip()))
    return results
