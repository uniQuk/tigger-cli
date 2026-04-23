"""Single source of truth for app identity and paths."""
from __future__ import annotations
import pathlib

APP_NAME = "tigger"
CLI_COMMAND = "tigger-code"
CONFIG_DIR = ".tigger"
VERSION = "0.1.0"


def home_config_dir() -> pathlib.Path:
    """Return ~/.tigger/ path."""
    return pathlib.Path.home() / CONFIG_DIR


def project_config_dir(project_dir: pathlib.Path) -> pathlib.Path:
    """Return <project>/.tigger/ path."""
    return project_dir / CONFIG_DIR
