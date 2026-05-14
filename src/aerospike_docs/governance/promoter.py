# -*- coding: utf-8 -*-
"""Promotion service for merging terms to glossary."""

import subprocess
import sys
import yaml
from pathlib import Path
from typing import Dict, Any, List

from aerospike_docs.base import BaseService
from aerospike_docs.core.config import ApiConfig
from aerospike_docs.core.logging import get_logger


class PromotionService(BaseService):
    """Service for promoting cleaned terms to the master glossary.

    Merges validated terms into glossary.yaml (SSOT).
    """

    def __init__(self, api_config: ApiConfig, scripts_dir: Path, timeout: int = 120):
        super().__init__(api_config)
        self.scripts_dir = scripts_dir
        self.timeout = timeout
        self._script_name = "promote_terms.py"

    def execute(self, terms_file: str = None, **kwargs) -> Dict[str, Any]:
        """Execute term promotion to glossary.

        Args:
            terms_file: Path to cleaned terms file
            **kwargs: Additional options

        Returns:
            Dict containing promotion results
        """
        self._logger.info(f"Starting term promotion: {terms_file}")

        try:
            result = self._run_promotion_script(terms_file, **kwargs)

            if result.returncode == 0:
                self._logger.info("Promotion completed successfully")
                return {"success": True, "message": "Terms promoted to glossary successfully"}
            else:
                error_msg = result.stderr or "Unknown error during promotion"
                self._logger.error(f"Promotion failed: {error_msg}")
                return {"success": False, "error": error_msg}

        except subprocess.TimeoutExpired as e:
            self._logger.error(f"Promotion timed out: {e}")
            return {"success": False, "error": f"Timeout expired: {e}"}
        except FileNotFoundError as e:
            self._logger.error(f"Script not found: {e}")
            return {"success": False, "error": f"Script not found: {e}"}
        except (FileNotFoundError, PermissionError, OSError) as e:
            self._logger.error(f"OS error during promotion: {e}")
            return {"success": False, "error": f"File system error: {e}"}
        except (ValueError, TypeError, KeyError) as e:
            self._logger.exception("Promotion failed: invalid data")
            return {"success": False, "error": f"Invalid data: {e}"}

    def _run_promotion_script(self, terms_file: str = None, **kwargs) -> subprocess.CompletedProcess:
        """Run the promotion script as subprocess.

        Args:
            terms_file: Path to terms file
            **kwargs: Additional arguments

        Returns:
            CompletedProcess result
        """
        script_path = self.scripts_dir / self._script_name

        cmd = [sys.executable, str(script_path)]

        if terms_file:
            cmd.extend(["--file", terms_file])

        timeout = kwargs.get("timeout", self.timeout)

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
            cwd=self.scripts_dir.parent
        )

        return result

    def validate(self, terms_file: str = None, **kwargs) -> bool:
        """Validate promotion parameters.

        Args:
            terms_file: Path to terms file
            **kwargs: Additional parameters

        Returns:
            True if valid
        """
        if terms_file is None:
            return True  # Will use default

        # Check file exists
        return Path(terms_file).exists()

    def get_glossary_terms(self) -> List[Dict[str, Any]]:
        """Get all terms from glossary.

        Returns:
            List of glossary terms
        """
        glossary_file = self.scripts_dir.parent / "glossary.yaml"

        if not glossary_file.exists():
            return []

        try:
            with open(glossary_file, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
                return data.get("entities", []) if data else []
        except yaml.YAMLError as e:
            self._logger.warning(f"Failed to parse glossary (invalid YAML): {e}")
            return []
        except OSError as e:
            self._logger.warning(f"Failed to read glossary: {e}")
            return []
