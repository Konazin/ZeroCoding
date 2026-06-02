
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def get_project_root():
    return PROJECT_ROOT
