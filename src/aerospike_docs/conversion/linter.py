# -*- coding: utf-8 -*-
"""
Markdown Linter Service - DDD Domain Service for Markdown Validation

Validates Markdown files against the DocOps Markdown Standard SOP:
- YAML Frontmatter validation
- Heading hierarchy validation
- Bold tags for roles and form IDs
- Table usage for deliverables

Exit codes:
    0 = Validation passed
    1 = Validation failed (see stderr for details)
"""

import re
from aerospike_docs.core.document_codes import form_id_patterns, load_doc_prefixes
import yaml
from pathlib import Path
from typing import List, Tuple, Dict, Any


# ============================================================================
# Validation Models
# ============================================================================

class ValidationError:
    """Single validation error."""

    def __init__(self, line_number: int, message: str):
        self.line_number = line_number
        self.message = message

    def __str__(self):
        return f"Line {self.line_number}: {self.message}"


# ============================================================================
# MarkdownLinter Service
# ============================================================================

class MarkdownLinter:
    """
    Markdown Linter Service - validates Markdown files against DocOps SOP.

    Provides comprehensive validation including:
    - YAML frontmatter presence and required fields
    - Heading hierarchy (no level skipping)
    - Bold formatting for roles and form IDs
    - Table usage for deliverables
    """

    # Common role patterns (Chinese)
    ROLE_PATTERNS = [
        r'(?<!\*)\b(工装|工艺|检验|技术|管理|负责|保管|审批|审核)[员人师部局长队组]*(?!\*)',
    ]

    # Form ID patterns
    FORM_PATTERNS = form_id_patterns()

    # Deliverable keywords
    DELIVERABLE_KEYWORDS = ['表格', '表单', '交付物', '记录', '附件']

    # Required frontmatter fields
    REQUIRED_FIELDS = ['id', 'title', 'version', 'department']

    def __init__(self, strict_mode: bool = False, project_root: Path = None):
        """
        Initialize Markdown Linter.

        Args:
            strict_mode: If True, apply stricter validation rules
        """
        self.strict_mode = strict_mode
        prefixes = load_doc_prefixes(project_root)
        self.form_patterns = form_id_patterns(prefixes)

    def validate_file(self, file_path: str) -> Tuple[bool, List[ValidationError]]:
        """
        Validate a Markdown file against the DocOps Standard.

        Args:
            file_path: Path to the Markdown file

        Returns:
            Tuple of (is_valid, errors_list)
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except FileNotFoundError:
            return False, [ValidationError(0, f"File not found: {file_path}")]
        except Exception as e:
            return False, [ValidationError(0, f"Error reading file: {e}")]

        return self.validate_content(content)

    def validate_content(self, content: str) -> Tuple[bool, List[ValidationError]]:
        """
        Validate Markdown content.

        Args:
            content: Markdown content string

        Returns:
            Tuple of (is_valid, errors_list)
        """
        all_errors = []

        # Run all validations
        all_errors.extend(self.validate_yaml_frontmatter(content))
        all_errors.extend(self.validate_heading_hierarchy(content))
        all_errors.extend(self.validate_bold_roles_and_forms(content))
        all_errors.extend(self.validate_deliverable_tables(content))

        return len(all_errors) == 0, all_errors

    def validate_yaml_frontmatter(self, content: str) -> List[ValidationError]:
        """Validate YAML frontmatter presence and required fields."""
        errors = []

        # Check for frontmatter
        if not content.startswith('---'):
            errors.append(ValidationError(1, "Missing YAML frontmatter (must start with '---')"))
            return errors

        # Find end of frontmatter
        lines = content.split('\n')
        frontmatter_end = -1
        for i, line in enumerate(lines[1:], 1):
            if line.strip() == '---':
                frontmatter_end = i
                break

        if frontmatter_end == -1:
            errors.append(ValidationError(1, "Unclosed YAML frontmatter"))
            return errors

        # Parse frontmatter
        frontmatter_text = '\n'.join(lines[1:frontmatter_end])
        try:
            front_matter = yaml.safe_load(frontmatter_text)
        except yaml.YAMLError as e:
            errors.append(ValidationError(2, f"Invalid YAML: {e}"))
            return errors

        # Check required fields
        for field in self.REQUIRED_FIELDS:
            if field not in front_matter:
                errors.append(ValidationError(2, f"Missing required frontmatter field: {field}"))

        return errors

    def validate_heading_hierarchy(self, content: str) -> List[ValidationError]:
        """Validate heading hierarchy (H1 -> H2 -> H3, no skipping)."""
        errors = []
        lines = content.split('\n')

        heading_pattern = re.compile(r'^(#{1,6})\s+(.+)$')
        current_level = 0

        for i, line in enumerate(lines, 1):
            match = heading_pattern.match(line)
            if match:
                level = len(match.group(1))

                # First heading should be H1
                if current_level == 0:
                    if level != 1:
                        errors.append(ValidationError(i, f"First heading must be H1, found H{level}"))
                    current_level = level
                else:
                    # Check for skipping (e.g., H2 -> H4)
                    if level > current_level + 1:
                        errors.append(ValidationError(i,
                            f"Heading skip: H{current_level} -> H{level} (should be sequential)"))
                    current_level = level

        return errors

    def validate_bold_roles_and_forms(self, content: str) -> List[ValidationError]:
        """Validate that roles and form IDs are wrapped in bold tags."""
        errors = []

        lines = content.split('\n')

        # Skip frontmatter
        in_frontmatter = False
        content_start = 0
        for i, line in enumerate(lines):
            if line.strip() == '---':
                if not in_frontmatter:
                    in_frontmatter = True
                else:
                    content_start = i + 1
                    break

        # Check lines (excluding headings and code blocks)
        in_code_block = False
        for i, line in enumerate(lines[content_start:], content_start + 1):
            # Track code blocks
            if '```' in line:
                in_code_block = not in_code_block
                continue

            if in_code_block:
                continue

            # Skip heading lines
            if line.strip().startswith('#'):
                continue

            # Check for form IDs not in bold
            for pattern in self.form_patterns:
                matches = re.finditer(pattern, line, re.IGNORECASE)
                for match in matches:
                    # Check if already wrapped in **
                    start = match.start()
                    end = match.end()
                    before = line[max(0, start-1):start]
                    after = line[end:min(len(line), end+1)]

                    if before != '*' and after != '*':
                        errors.append(ValidationError(i,
                            f"Form ID '{match.group()}' should be wrapped in **bold**"))

        return errors

    def validate_deliverable_tables(self, content: str) -> List[ValidationError]:
        """Validate that deliverables use tables, not bullet lists."""
        errors = []

        lines = content.split('\n')

        in_deliverable_section = False
        for i, line in enumerate(lines, 1):
            # Check if entering deliverable section
            if any(kw in line for kw in self.DELIVERABLE_KEYWORDS):
                in_deliverable_section = True

            # Check for bullet list in deliverable section
            if in_deliverable_section:
                stripped = line.strip()
                if stripped.startswith('- ') or stripped.startswith('* '):
                    # Check if it's followed by a table
                    if i < len(lines):
                        next_line = lines[i].strip()
                        if not next_line.startswith('|'):
                            errors.append(ValidationError(i,
                                "Deliverable section uses bullet list. Use tables instead."))

            # Exit deliverable section on next heading
            if in_deliverable_section and line.strip().startswith('#'):
                in_deliverable_section = False

        return errors

    def validate_batch(self, file_paths: List[str]) -> Dict[str, Tuple[bool, List[ValidationError]]]:
        """
        Validate multiple files.

        Args:
            file_paths: List of file paths

        Returns:
            Dict mapping file path to (is_valid, errors) tuple
        """
        results = {}
        for file_path in file_paths:
            results[file_path] = self.validate_file(file_path)
        return results

    def get_validation_summary(self, results: Dict[str, Tuple[bool, List[ValidationError]]]) -> Dict[str, Any]:
        """
        Get summary of validation results.

        Args:
            results: Results from validate_batch

        Returns:
            Summary dict with pass/fail counts
        """
        total = len(results)
        passed = sum(1 for is_valid, _ in results.values() if is_valid)
        failed = total - passed

        return {
            "total": total,
            "passed": passed,
            "failed": failed,
            "pass_rate": passed / total if total > 0 else 0
        }


# ============================================================================
# CLI Entry Point
# ============================================================================

def main():
    """Main entry point for CLI usage."""
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description='DocOps Markdown Linter - Validate Markdown files against standard SOP'
    )
    parser.add_argument('files', nargs='+', help='Markdown files to validate')
    parser.add_argument('--verbose', '-v', action='store_true', help='Show all errors')

    args = parser.parse_args()

    linter = MarkdownLinter()
    has_errors = False

    for file_path in args.files:
        is_valid, errors = linter.validate_file(file_path)

        if is_valid:
            print(f"PASSED {file_path}: PASSED")
        else:
            print(f"FAILED {file_path}: FAILED", file=sys.stderr)
            has_errors = True
            for error in errors:
                print(f"   {error}", file=sys.stderr)

    # Exit with non-zero code if any validation failed
    sys.exit(1 if has_errors else 0)


if __name__ == '__main__':
    main()
