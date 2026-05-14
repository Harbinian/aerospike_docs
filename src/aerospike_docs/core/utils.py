# -*- coding: utf-8 -*-
"""Core utility functions."""

import logging
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def validate_path(path: str, project_root: Path) -> str:
    """Validate path security.

    Args:
        path: Path string to validate
        project_root: Root directory to validate against

    Returns:
        Validated path string, or empty string if invalid
    """
    if not path:
        return ""
    dangerous = ['..', '~', '${', '$(']
    for p in dangerous:
        if p in path:
            logger.warning(f"Dangerous pattern '{p}' detected in path: {path}")
            return ""
    try:
        p = Path(path)
        resolved = (project_root / p).resolve()
        resolved.relative_to(project_root.resolve())
        return str(p)
    except Exception as e:
        logger.warning(f"Path validation failed: {path} - {e}")
        return ""


def clean_text(text: str) -> str:
    """Clean text by removing extra whitespace and special characters.

    Args:
        text: Raw text

    Returns:
        Cleaned text
    """
    if not text:
        return ""

    # Replace multiple whitespace chars with single space
    text = re.sub(r"[ \t]+", " ", text)
    # Remove zero-width characters (U+200B through U+200F, U+202A through U+202F)
    text = re.sub(r"[​-‏‪- ]", "", text)
    # Normalize newlines
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Strip leading/trailing whitespace
    text = text.strip()

    return text


def write_file_with_utf8(filepath: str, content: str) -> bool:
    """Write file with UTF-8 encoding (BOM for Windows compatibility).

    Args:
        filepath: File path
        content: File content

    Returns:
        True if write succeeded
    """
    try:
        with open(filepath, "w", encoding="utf-8-sig") as f:
            f.write(content)
        return True
    except Exception as e:
        logger.error(f"Failed to write file {filepath}: {e}")
        return False
