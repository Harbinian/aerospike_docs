# -*- coding: utf-8 -*-
"""Core utility functions."""

import logging
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
