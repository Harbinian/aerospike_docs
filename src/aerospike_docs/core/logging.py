# -*- coding: utf-8 -*-
"""Logging module for aerospike_docs."""

import logging
import sys
from pathlib import Path
from typing import Optional, Any
from logging.handlers import RotatingFileHandler


def setup_logging(
    level: int = logging.INFO,
    log_file: Optional[Path] = None,
    log_dir: Optional[Path] = None,
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 5,
    enable_console: bool = True,
    enable_file: bool = True,
) -> logging.Logger:
    """Set up centralized logging configuration."""
    if log_dir is None:
        log_dir = Path("logs")
    log_dir.mkdir(parents=True, exist_ok=True)

    if log_file is None:
        log_file = log_dir / "aerospike_docs.log"

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.handlers.clear()

    format_string = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"
    console_format = "%(levelname)s: %(message)s"

    formatter = logging.Formatter(format_string, date_format)
    console_formatter = logging.Formatter(console_format, date_format)

    if enable_console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        console_handler.setFormatter(console_formatter)
        root_logger.addHandler(console_handler)

    if enable_file and log_file:
        file_handler = RotatingFileHandler(
            log_file, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("PIL").setLevel(logging.WARNING)

    return root_logger


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance with the specified name."""
    return logging.getLogger(name)


def setup_subprocess_logging(
    log_dir: Optional[Path] = None,
    subprocess_name: str = "subprocess",
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 3,
) -> logging.Logger:
    """Set up logging for subprocess operations."""
    if log_dir is None:
        log_dir = Path("logs")
    log_dir.mkdir(parents=True, exist_ok=True)

    subprocess_log = log_dir / f"{subprocess_name}.log"
    logger = logging.getLogger(f"aerospike_docs.{subprocess_name}")
    logger.setLevel(logging.INFO)

    file_handler = RotatingFileHandler(
        subprocess_log, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
    )
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        "%Y-%m-%d %H:%M:%S"
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger


def get_subprocess_logger(name: str) -> logging.Logger:
    """Get a logger for subprocess operations."""
    logger = logging.getLogger(f"aerospike_docs.subprocess.{name}")
    if not logger.handlers:
        log_dir = Path("logs")
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "subprocess.log"
        file_handler = RotatingFileHandler(
            log_file, maxBytes=10 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            "%Y-%m-%d %H:%M:%S"
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        logger.setLevel(logging.INFO)
    return logger


def set_log_level(level: int, logger_name: Optional[str] = None) -> None:
    """Set logging level for a specific logger or root logger."""
    if logger_name:
        logging.getLogger(logger_name).setLevel(level)
    else:
        logging.getLogger().setLevel(level)


class ServiceLogger:
    """Logger wrapper with service-specific features."""

    def __init__(self, logger: logging.Logger, service_name: str):
        self._logger = logger
        self._service_name = service_name

    def log_execution(self, method: str, **kwargs) -> None:
        params = ", ".join(f"{k}={v}" for k, v in kwargs.items())
        self._logger.info(f"[{self._service_name}] Executing {method}({params})")

    def log_result(self, method: str, result: Any) -> None:
        self._logger.info(f"[{self._service_name}] {method} completed: {result}")

    def log_error(self, method: str, error: Exception) -> None:
        self._logger.error(f"[{self._service_name}] {method} failed: {error}", exc_info=True)
