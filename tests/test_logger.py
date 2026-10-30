"""Tests for core/logger.py — file-handler fallback (S1-B2) + rotation (S6-B19)."""
from __future__ import annotations

import importlib
import logging
import logging.handlers


def _fresh_logger():
    """Return the cadagent logger with handlers cleared for a clean setup."""
    lg = logging.getLogger("cadagent")
    lg.handlers.clear()
    return lg


def test_file_handler_failure_degrades_to_console_only(monkeypatch):
    """Import must not crash when no log location is writable."""
    import core.logger as logger_mod

    lg = _fresh_logger()

    def boom(*args, **kwargs):
        raise OSError("simulated unwritable location")

    monkeypatch.setattr(logging.handlers, "RotatingFileHandler", boom)
    try:
        importlib.reload(logger_mod)
        assert lg.handlers == []
        # Logging still works (no-op without a handler, never raises)
        logger_mod.log_info("degraded mode message")
    finally:
        monkeypatch.undo()
        lg.handlers.clear()
        importlib.reload(logger_mod)  # re-establish the real file handler
        assert len(lg.handlers) == 1


def test_normal_setup_attaches_rotating_file_handler():
    import core.logger as logger_mod

    lg = _fresh_logger()
    importlib.reload(logger_mod)
    assert len(lg.handlers) == 1
    fh = lg.handlers[0]
    # RotatingFileHandler IS a FileHandler subclass; assert the rotation
    # config explicitly (S6-B19: 5 MB x 3 backups).
    assert isinstance(fh, logging.handlers.RotatingFileHandler)
    assert fh.maxBytes == 5 * 1024 * 1024
    assert fh.backupCount == 3
