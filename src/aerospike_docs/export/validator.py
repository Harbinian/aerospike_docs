# -*- coding: utf-8 -*-
"""Data Validator Domain Service.

Encapsulates data validation logic for exports.
"""

import sys
from pathlib import Path
from typing import Dict, Any, List, Optional

# Add project root to path (for backward compatibility with Norms imports)
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


class DataValidator:
    """Domain Service for validating glossary data integrity.

    This is the gatekeeper that MUST pass before any export operation.
    """

    def __init__(self, project_root: Path = None,
                 glossary_validator_class: Optional[type] = None):
        """Initialize DataValidator.

        Args:
            project_root: Root directory of the project
            glossary_validator_class: Optional GlossaryValidator class for
                validation. If not provided, falls back to basic checks.
        """
        self.project_root = project_root or PROJECT_ROOT
        self.glossary_path = self.project_root / "glossary.yaml"
        self._validator_class = glossary_validator_class

    def validate_glossary(self) -> bool:
        """Validate glossary using the validation service.

        Returns:
            True if validation passes
        """
        # Try injected validator first
        if self._validator_class is not None:
            try:
                validator = self._validator_class(str(self.glossary_path))
                if hasattr(validator, 'load_file') and not validator.load_file():
                    return False
                result = validator.validate()
                return result.passed
            except Exception as e:
                print(f"Validation error: {e}")
                return False

        # Try importing from Norms validation service (backward compatibility)
        try:
            from services.validation.validator import GlossaryValidator
            validator = GlossaryValidator(str(self.glossary_path))
            if not validator.load_file():
                return False
            result = validator.validate()
            return result.passed
        except (ImportError, Exception) as e:
            print(f"Validation error: {e}")
            return False

    def quick_check(self) -> bool:
        """Quick validation check without running full validation.

        Returns:
            True if basic checks pass
        """
        if not self.glossary_path.exists():
            return False

        # Basic file check
        return self.glossary_path.stat().st_size > 0

    def validate(self) -> bool:
        """Validate glossary data.

        Returns:
            True if valid
        """
        return self.validate_glossary()

    def execute(self, **kwargs) -> Dict[str, Any]:
        """Execute data validation.

        Args:
            **kwargs: Additional options

        Returns:
            Dict containing validation results
        """
        print("=" * 60)
        print("DataValidator - Glossary Validation")
        print("=" * 60)

        # Quick check first
        if not self.quick_check():
            return {
                "success": False,
                "error": "glossary.yaml not found or empty",
                "valid": False
            }

        # Full validation
        if self.validate_glossary():
            print("\n[OK] Validation passed")
            return {"success": True, "message": "Data validation passed", "valid": True}
        else:
            print("\n[ERROR] Validation failed")
            return {"success": False, "error": "Validation failed", "valid": False}
