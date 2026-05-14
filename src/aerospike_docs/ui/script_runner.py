# -*- coding: utf-8 -*-
"""Script runner with security validation."""

import subprocess
import sys
from pathlib import Path
from typing import List, Optional

from aerospike_docs.core.logging import get_logger

logger = get_logger(__name__)


def run_script(script_name: str, scripts_dir: Path,
               args: Optional[List[str]] = None, timeout: int = 300) -> tuple:
    """Run a Python script with security checks.

    Returns:
        tuple: (success: bool, stdout: str, stderr: str)
    """
    # Path traversal defense
    if not script_name or '/' in script_name or '\\' in script_name or '..' in script_name:
        return False, "", "Invalid script name: path traversal detected"

    # Command injection defense
    if args:
        dangerous_patterns = [';', '|', '&&', '||', '>', '>>', '<', '`', '$(', '\n', '\r']
        for arg in args:
            if any(pattern in arg for pattern in dangerous_patterns):
                logger.warning(f"[run_script] Blocked dangerous argument: {arg}")
                return False, "", f"Invalid argument: dangerous pattern detected"

    script_path = scripts_dir / script_name
    if not script_path.exists():
        return False, "", f"Script not found: {script_name}"

    cmd = [sys.executable, str(script_path)]
    if args:
        cmd.extend(args)

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            encoding='utf-8', timeout=timeout,
            errors='replace'
        )
        log_msg = f"[run_script] {script_name} {' '.join(args or [])} -> returncode={result.returncode}"
        logger.info(log_msg)

        if result.returncode != 0:
            err_msg = result.stderr.strip() if result.stderr else f"Script exited with code {result.returncode}"
            logger.warning(f"[run_script] Script failed: {err_msg}")
            return False, result.stdout, err_msg

        combined_output = result.stdout
        if result.stderr:
            combined_output += "\n[STDERR]\n" + result.stderr
        return True, combined_output, ""
    except subprocess.TimeoutExpired:
        err_msg = f"Script timed out after {timeout} seconds"
        logger.error(f"[run_script] Timeout: {script_name}")
        return False, "", err_msg
    except Exception as e:
        err_msg = str(e)
        logger.error(f"[run_script] Exception: {err_msg}")
        return False, "", err_msg
