"""Centralized logging for CadAgent FreeCAD workbench.

Writes to:
  1. FreeCAD.Console (when available)
  2. Log file: <FreeCAD user data>/CadAgent/cadagent.log
     Fallback: <temp>/CadAgent/cadagent.log
"""
from __future__ import annotations

import datetime
import logging
import os
import sys
import tempfile


def _get_log_dir() -> str:
    """Use project directory Mod/CadAgent/log for log files."""
    # Get the core module directory (core/logger.py)
    base = os.path.dirname(os.path.abspath(__file__))
    # Go up to CadAgent root
    base = os.path.dirname(base)
    d = os.path.join(base, "log")
    os.makedirs(d, exist_ok=True)
    return d


def _setup_file_logger() -> logging.Logger:
    logger = logging.getLogger("cadagent")
    logger.setLevel(logging.DEBUG)
    if logger.handlers:
        return logger
    log_path = os.path.join(_get_log_dir(), "cadagent.log")
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    ))
    logger.addHandler(fh)
    return logger


_file_logger = _setup_file_logger()


def _log(msg: str, level: str = "warning") -> None:
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    full = f"[{ts}] {msg}"
    # Console
    try:
        import FreeCAD
        if level == "error":
            FreeCAD.Console.PrintError(f"[CadAgent] {full}\n")
        elif level == "warning":
            FreeCAD.Console.PrintWarning(f"[CadAgent] {full}\n")
        else:
            FreeCAD.Console.PrintMessage(f"[CadAgent] {full}\n")
    except (ImportError, AttributeError):
        prefix = {"error": "ERROR", "warning": "WARN", "info": "INFO"}.get(level, "LOG")
        print(f"[CadAgent] {prefix}: {full}", file=sys.stderr)
    # File
    log_level = {"error": logging.ERROR, "warning": logging.WARNING, "info": logging.INFO}.get(level, logging.INFO)
    _file_logger.log(log_level, msg)


def log_info(msg: str) -> None:
    _log(msg, "info")


def log_warning(msg: str) -> None:
    _log(msg, "warning")


def log_error(msg: str) -> None:
    _log(msg, "error")
