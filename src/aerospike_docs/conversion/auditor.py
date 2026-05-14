# -*- coding: utf-8 -*-
"""Conversion auditor service for tracking conversion history."""

import csv
import os
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime

from aerospike_docs.base import BaseService
from aerospike_docs.core.config import ApiConfig
from aerospike_docs.core.logging import get_logger


class ConversionAuditor(BaseService):
    """Service for auditing document conversion operations.

    Tracks conversion history, errors, and generates audit reports.
    """

    def __init__(self, api_config: ApiConfig,
                 outputs_dir: Path = None, reports_dir: Path = None):
        """Initialize ConversionAuditor.

        Args:
            api_config: API configuration instance
            outputs_dir: Directory containing converted outputs
            reports_dir: Directory for audit reports
        """
        super().__init__(api_config)
        self._outputs_dir = outputs_dir or Path(__file__).parent.parent / "outputs"
        self._report_dir = reports_dir or Path(__file__).parent.parent / "reports"
        self._report_dir.mkdir(exist_ok=True)

    def execute(self, **kwargs) -> Dict[str, Any]:
        """Execute audit report generation.

        Args:
            **kwargs: Additional options

        Returns:
            Dict containing audit results
        """
        self._logger.info("Generating conversion audit report")

        try:
            # Scan outputs directory for converted files
            outputs_dir = self._outputs_dir

            if not outputs_dir.exists():
                return {"success": False, "error": "Outputs directory does not exist"}

            files = list(outputs_dir.rglob("*.md"))

            # Generate report
            report_data = self._scan_converted_files(files)

            # Save report
            self._save_report(report_data)

            self._logger.info(f"Audit report generated: {len(files)} files scanned")
            return {"success": True, "files_scanned": len(files), "data": report_data}

        except PermissionError as e:
            self._logger.error(f"Permission denied: {e}")
            return {"success": False, "error": f"Permission denied: {e}"}
        except (FileNotFoundError, PermissionError, OSError) as e:
            self._logger.error(f"OS error during audit: {e}")
            return {"success": False, "error": f"File system error: {e}"}
        except (ValueError, TypeError, KeyError) as e:
            self._logger.exception("Audit generation failed: invalid data")
            return {"success": False, "error": f"Invalid data: {e}"}

    def _scan_converted_files(self, files: List[Path]) -> List[Dict[str, Any]]:
        """Scan converted files and extract metadata.

        Args:
            files: List of converted Markdown files

        Returns:
            List of file metadata dictionaries
        """
        results = []

        for file_path in files:
            try:
                stat = file_path.stat()
                results.append({
                    "Source File": file_path.name,
                    "Size (bytes)": stat.st_size,
                    "Modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    "Status": "audited"
                })
            except OSError as e:
                self._logger.warning(f"Failed to scan {file_path}: {e}")

        return results

    def _save_report(self, data: List[Dict[str, Any]]) -> None:
        """Save audit report to CSV.

        Args:
            data: List of audit records
        """
        report_file = self._report_dir / "conversion_audit.csv"

        if not data:
            return

        try:
            with open(report_file, 'w', newline='', encoding='utf-8') as f:
                if data:
                    writer = csv.DictWriter(f, fieldnames=data[0].keys())
                    writer.writeheader()
                    writer.writerows(data)

            self._logger.info(f"Audit report saved to {report_file}")

        except csv.Error as e:
            self._logger.error(f"Failed to save audit report (CSV error): {e}")
        except OSError as e:
            self._logger.error(f"Failed to save audit report: {e}")

    def get_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get conversion history.

        Args:
            limit: Maximum number of records to return

        Returns:
            List of conversion history records
        """
        report_file = self._report_dir / "conversion_audit.csv"

        if not report_file.exists():
            return []

        try:
            with open(report_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                return list(reader)[:limit]
        except csv.Error as e:
            self._logger.warning(f"Failed to read audit history (CSV error): {e}")
            return []
        except OSError as e:
            self._logger.warning(f"Failed to read audit history: {e}")
            return []

    def validate(self, **kwargs) -> bool:
        """Validate audit parameters.

        Args:
            **kwargs: Parameters to validate

        Returns:
            True if valid
        """
        return True
