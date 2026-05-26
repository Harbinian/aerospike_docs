# -*- coding: utf-8 -*-
"""
Glossary Validation Service

Domain service for validating glossary.yaml data integrity.
"""

from pathlib import Path
from typing import Set, Dict, List, Any
from collections import defaultdict


class ValidationResult:
    """Container for validation results."""

    def __init__(self):
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.info: List[str] = []

    def add_error(self, message: str, line_no: int = None):
        if line_no:
            self.errors.append(f"Line {line_no}: {message}")
        else:
            self.errors.append(message)

    def add_warning(self, message: str, line_no: int = None):
        if line_no:
            self.warnings.append(f"Line {line_no}: {message}")
        else:
            self.warnings.append(message)

    def add_info(self, message: str):
        self.info.append(message)

    @property
    def passed(self) -> bool:
        return len(self.errors) == 0


class GlossaryValidator:
    """Validator for glossary.yaml structure and data integrity."""

    VALID_RISK_LEVELS = {'High', 'Medium', 'Low', 'N/A', None}
    VALID_DOC_CATEGORIES = {'管理制度', '技术规范', '作业指导', '文档类型'}
    VALID_TOOLING_CATEGORIES = {'工装类型', '工装子类型', '模具类型', '夹具类型'}

    def __init__(self, filepath: str):
        self.filepath = Path(filepath)
        self.entities: List[Dict[str, Any]] = []
        self.entity_ids: Set[str] = set()
        self.entity_id_to_line: Dict[str, int] = {}
        self.line_cache: Dict[int, str] = {}

    def load_file(self) -> bool:
        """Load and parse the YAML file."""
        import yaml

        if not self.filepath.exists():
            print(f"[ERROR] File not found: {self.filepath}")
            return False

        try:
            with open(self.filepath, 'r', encoding='utf-8') as f:
                content = f.read()

            for i, line in enumerate(content.splitlines(), 1):
                self.line_cache[i] = line

            data = yaml.safe_load(content)
            if not data or 'entities' not in data:
                print(f"[ERROR] Invalid YAML: missing 'entities' key")
                return False

            self.entities = data.get('entities', [])
            print(f"\nLoaded {len(self.entities)} entities")
            return True

        except yaml.YAMLError as e:
            print(f"[ERROR] YAML parsing error: {e}")
            return False

    def _find_line_for_entity(self, entity_id: str) -> int:
        if entity_id in self.entity_id_to_line:
            return self.entity_id_to_line[entity_id]

        id_pattern = f"id: {entity_id}"
        for line_no, line in self.line_cache.items():
            if id_pattern in line:
                self.entity_id_to_line[entity_id] = line_no
                return line_no

        return 1

    def validate(self) -> ValidationResult:
        """Run all validation checks."""
        result = ValidationResult()
        self._build_id_index(result)

        if not result.passed:
            return result

        self._check_unique_ids(result)
        self._check_parent_references(result)
        self._check_target_entity_references(result)
        self._check_risk_level_values(result)
        self._check_category_non_empty(result)
        self._check_orphans(result)
        self._check_circular_dependencies(result)

        return result

    def _build_id_index(self, result: ValidationResult):
        for entity in self.entities:
            entity_id = entity.get('id', '')
            if entity_id:
                self.entity_ids.add(entity_id)

    def _check_unique_ids(self, result: ValidationResult):
        seen = set()
        for entity in self.entities:
            entity_id = entity.get('id', '')
            if entity_id:
                if entity_id in seen:
                    line_no = self._find_line_for_entity(entity_id)
                    result.add_error(f"Duplicate entity ID: '{entity_id}'", line_no)
                seen.add(entity_id)

    def _check_parent_references(self, result: ValidationResult):
        for entity in self.entities:
            parent = entity.get('parent', '')
            if parent and parent not in self.entity_ids:
                line_no = self._find_line_for_entity(entity.get('id', ''))
                result.add_error(
                    f"Invalid parent reference: '{parent}' does not exist. "
                    f"Entity: {entity.get('name', 'Unknown')}",
                    line_no
                )

    def _check_target_entity_references(self, result: ValidationResult):
        for entity in self.entities:
            target = entity.get('target_entity', '')
            if target and target not in self.entity_ids:
                line_no = self._find_line_for_entity(entity.get('id', ''))
                result.add_error(
                    f"Invalid target_entity reference: '{target}' does not exist. "
                    f"Process: {entity.get('name', 'Unknown')}",
                    line_no
                )

    def _check_risk_level_values(self, result: ValidationResult):
        for entity in self.entities:
            if entity.get('is_process', False):
                continue
            risk_level = entity.get('attributes', {}).get('risk_level')
            if risk_level is not None and risk_level not in self.VALID_RISK_LEVELS:
                line_no = self._find_line_for_entity(entity.get('id', ''))
                result.add_error(
                    f"Invalid risk_level: '{risk_level}'. "
                    f"Must be in {sorted(self.VALID_RISK_LEVELS - {None})}",
                    line_no
                )

    def _check_category_non_empty(self, result: ValidationResult):
        for entity in self.entities:
            category = entity.get('category', '')
            if not category or not category.strip():
                line_no = self._find_line_for_entity(entity.get('id', ''))
                result.add_error(
                    f"Empty category field. Entity: {entity.get('name', 'Unknown')}",
                    line_no
                )

    def _check_orphans(self, result: ValidationResult):
        for entity in self.entities:
            if entity.get('is_root', False) or entity.get('is_process', False):
                continue
            parent = entity.get('parent', '')
            if not parent:
                entity_id = entity.get('id', '')
                entity_name = entity.get('name', '')
                line_no = self._find_line_for_entity(entity_id)

                if not any(x in entity_id for x in ['_Tooling', '_Doc']):
                    continue

                result.add_error(
                    f"Orphan entity: '{entity_id}' ({entity_name}) has no parent.",
                    line_no
                )

    def _check_circular_dependencies(self, result: ValidationResult):
        parent_map: Dict[str, str] = {}
        for entity in self.entities:
            entity_id = entity.get('id', '')
            parent = entity.get('parent', '')
            if entity_id and parent:
                parent_map[entity_id] = parent

        for entity_id in parent_map:
            visited = set()
            current = entity_id
            path = []

            while current in parent_map and current not in visited:
                visited.add(current)
                path.append(current)
                current = parent_map[current]

            if current in visited and current in parent_map.values():
                cycle_start = path.index(current)
                cycle_path = path[cycle_start:] + [current]
                cycle_str = ' -> '.join(cycle_path)
                line_no = self._find_line_for_entity(entity_id)
                result.add_error(f"Circular dependency: {cycle_str}", line_no)
