# -*- coding: utf-8 -*-
"""Cleaning service for terminology data quality."""

import json
import re
import subprocess
import sys
import yaml
from pathlib import Path
from typing import Dict, Any, List, Set, Tuple
from dataclasses import dataclass, field
from collections import defaultdict

from aerospike_docs.base import BaseService
from aerospike_docs.core.config import ApiConfig
from aerospike_docs.core.logging import get_logger

# ============================================================================
# YAML Frontmatter Pattern
# ============================================================================
FRONTMATTER_PATTERN = re.compile(r'^---\s*\n(.*?)\n---\s*\n', re.DOTALL)
WIKILINK_PATTERN = re.compile(r'\[\[([^\]|]+)\]\]')

# ============================================================================
# Data Models
# ============================================================================

@dataclass
class Entity:
    """Entity definition for glossary."""
    id: str
    name: str
    aliases: List[str] = field(default_factory=list)
    en_term: str = ""
    category: str = ""
    description: str = ""
    source: str = ""


# ============================================================================
# TermCleaner Domain Service
# ============================================================================

class TermCleaner:
    """Domain Service for terminology cleaning and governance."""

    def __init__(self, config_path: str = "glossary.yaml"):
        self.config_path = config_path
        self.entities: Dict[str, Entity] = {}
        self.alias_to_id: Dict[str, str] = {}
        self.settings: Dict = {}
        self.file_concepts: Dict[str, Set[str]] = defaultdict(set)
        self.concept_backlinks: Dict[str, Set[str]] = defaultdict(set)
        self._aliases: Dict[str, List[str]] = {}
        self._load()
        self._load_aliases()

    def _load_aliases(self):
        config_path_obj = Path(self.config_path).resolve()
        project_root = config_path_obj.parent

        aliases_path = project_root / "data" / "aliases.json"
        if aliases_path.exists():
            with open(aliases_path, 'r', encoding='utf-8') as f:
                self._aliases = json.load(f)
            print(f"[INFO] Loaded {len(self._aliases)} aliases from aliases.json")

    def normalize_term(self, term: str) -> str:
        if not term or not self._aliases:
            return term
        for std_term, wild_terms in self._aliases.items():
            if term in wild_terms:
                return std_term
        return term

    def _load(self):
        if not Path(self.config_path).exists():
            raise FileNotFoundError(f"Config file not found: {self.config_path}")

        with open(self.config_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)

        for item in data.get('entities', []):
            entity = Entity(
                id=item['id'],
                name=item['name'],
                aliases=item.get('aliases', []),
                en_term=item.get('en_term', ''),
                category=item.get('category', ''),
                description=item.get('description', ''),
                source=item.get('source', '')
            )
            self.entities[entity.id] = entity

            for alias in entity.aliases:
                normalized = alias.lower().strip()
                if normalized in self.alias_to_id:
                    print(f"[WARNING] Alias conflict: '{alias}' belongs to multiple entities")
                self.alias_to_id[normalized] = entity.id

        self.settings = data.get('settings', {})
        print(f"[INFO] Loaded {len(self.entities)} entity definitions")
        print(f"[INFO] Loaded {len(self.alias_to_id)} alias mappings")

    def find_entities_in_text(self, text: str) -> Set[str]:
        found = set()
        text_lower = text.lower()

        for alias, entity_id in self.alias_to_id.items():
            if alias in text_lower:
                found.add(entity_id)

        normalized_found = set()
        for entity_id in found:
            entity = self.entities.get(entity_id)
            if entity:
                normalized_name = self.normalize_term(entity.name)
                for eid, ent in self.entities.items():
                    if ent.name == normalized_name:
                        normalized_found.add(eid)
                        break
                else:
                    normalized_found.add(entity_id)
            else:
                normalized_found.add(entity_id)

        return normalized_found

    def scan_directory(self, docs_dir: str) -> List[str]:
        docs_path = Path(docs_dir)

        if docs_dir in ("./outputs", "outputs", "./docs", "docs", "docs"):
            project_root = Path(self.config_path).resolve().parent
            docs_path = project_root / "refined_outputs"

        if not docs_path.exists():
            raise FileNotFoundError(
                f"[FATAL] refined_outputs directory not found at: {docs_path}\n"
                f"Pipeline broken: Term governance requires refined_outputs as single source of truth.\n"
                f"Please run document conversion first."
            )

        md_files = list(docs_path.rglob("*.md"))
        print(f"[INFO] Found {len(md_files)} Markdown files in {docs_path}")
        return [str(f) for f in md_files]

    def process_file(self, filepath: str) -> Tuple[bool, List[str]]:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        filename = Path(filepath).stem

        entities_found = self.find_entities_in_text(content)

        if not entities_found:
            return False, []

        for entity_id in entities_found:
            self.file_concepts[filename].add(entity_id)
            self.concept_backlinks[entity_id].add(filename)

        new_content, changes = self._inject_frontmatter(content, entities_found)

        if changes:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(new_content)
            print(f"✅ {filename}: Injected {len(entities_found)} concepts")
            for change in changes:
                print(f"   • {change}")

        return len(changes) > 0, changes

    def _inject_frontmatter(self, content: str, entities_found: Set[str]) -> Tuple[str, List[str]]:
        changes = []

        entities = [self.entities[eid] for eid in entities_found if eid in self.entities]

        existing_aliases = set()
        existing_concepts = set()

        match = FRONTMATTER_PATTERN.match(content)
        if match:
            yaml_content = match.group(1)

            alias_match = re.search(r'aliases:\s*\n((?:  - .+\n)*)', yaml_content)
            if alias_match:
                for line in alias_match.group(1).split('\n'):
                    alias = re.search(r'  - (.+)', line)
                    if alias:
                        existing_aliases.add(alias.group(1))

            concept_match = re.search(r'concepts:\s*\n((?:  - .+\n)*)', yaml_content)
            if concept_match:
                for line in concept_match.group(1).split('\n'):
                    concept = re.search(r'  - (.+)', line)
                    if concept:
                        existing_concepts.add(concept.group(1))

        new_aliases = set()
        for entity in entities:
            for alias in entity.aliases:
                if alias not in existing_aliases:
                    new_aliases.add(alias)

        new_concepts = set()
        for entity in entities:
            if entity.id not in existing_concepts:
                new_concepts.add(entity.id)

        if not match:
            frontmatter_parts = []

            if 'title:' not in content[:100]:
                title_match = re.search(r'^# (.+)$', content, re.MULTILINE)
                if title_match:
                    frontmatter_parts.append(f"title: {title_match.group(1)}")

            if new_aliases:
                frontmatter_parts.append("aliases:")
                for alias in sorted(new_aliases):
                    frontmatter_parts.append(f"  - {alias}")
                    changes.append(f"Add alias: {alias}")

            if new_concepts:
                frontmatter_parts.append("concepts:")
                for concept in sorted(new_concepts):
                    frontmatter_parts.append(f"  - {concept}")
                    changes.append(f"Add concept: {concept}")

            if frontmatter_parts:
                new_frontmatter = "---\n" + "\n".join(frontmatter_parts) + "\n---\n"
                content = new_frontmatter + content

        else:
            new_yaml_parts = []
            yaml_lines = match.group(1).split('\n')
            injected_aliases = False
            injected_concepts = False

            for line in yaml_lines:
                new_yaml_parts.append(line)

                if line.strip() == 'aliases:' and not injected_aliases:
                    for alias in sorted(new_aliases):
                        new_yaml_parts.append(f"  - {alias}")
                        changes.append(f"Add alias: {alias}")
                    injected_aliases = True

                if line.strip() == 'concepts:' and not injected_concepts:
                    for concept in sorted(new_concepts):
                        new_yaml_parts.append(f"  - {concept}")
                        changes.append(f"Add concept: {concept}")
                    injected_concepts = True

            if not injected_aliases and new_aliases:
                insert_idx = len(new_yaml_parts)
                new_yaml_parts.insert(insert_idx, "aliases:")
                for alias in sorted(new_aliases):
                    new_yaml_parts.insert(insert_idx + 1, f"  - {alias}")
                    changes.append(f"Add alias: {alias}")
                injected_aliases = True

            if not injected_concepts and new_concepts:
                insert_idx = len(new_yaml_parts)
                new_yaml_parts.insert(insert_idx, "concepts:")
                for concept in sorted(new_concepts):
                    new_yaml_parts.insert(insert_idx + 1, f"  - {concept}")
                    changes.append(f"Add concept: {concept}")
                injected_concepts = True

            new_yaml = "\n".join(new_yaml_parts)
            content = content.replace(match.group(0), f"---\n{new_yaml}\n---")

        return content, changes

    def generate_concept_cards(self, output_dir: str = "docs/concepts") -> int:
        import os
        os.makedirs(output_dir, exist_ok=True)

        count = 0

        for entity_id, entity in self.entities.items():
            backlinks = self.concept_backlinks.get(entity_id, set())
            content = self._render_concept_card(entity, backlinks)

            filepath = os.path.join(output_dir, f"{entity_id}.md")
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
            count += 1
            print(f"📇 Generate concept card: {entity_id}.md")

        return count

    def _render_concept_card(self, entity: Entity, backlinks: Set[str]) -> str:
        lines = []
        lines.append(f"# {entity.name}")
        lines.append("")
        lines.append("---")
        lines.append(f"id: {entity.id}")
        lines.append(f"name: {entity.name}")
        lines.append(f"aliases:")
        for alias in entity.aliases:
            lines.append(f"  - {alias}")
        lines.append(f"en_term: {entity.en_term}")
        lines.append(f"category: {entity.category}")
        lines.append("---")
        lines.append("")
        lines.append("## Standard Definition")
        lines.append("")
        lines.append(entity.description)
        lines.append("")
        if entity.en_term:
            lines.append("## English Term")
            lines.append("")
            lines.append(f"`{entity.en_term}`")
            lines.append("")
        if entity.aliases:
            lines.append("## Aliases / Variants")
            lines.append("")
            for alias in entity.aliases:
                lines.append(f"- {alias}")
            lines.append("")
        if entity.category:
            lines.append(f"**Category**: {entity.category}")
            lines.append("")
        if entity.source:
            lines.append(f"**Source**: {entity.source}")
            lines.append("")
        lines.append("---")
        lines.append("")
        lines.append("## Referenced By")
        lines.append("")
        if backlinks:
            for file in sorted(backlinks):
                lines.append(f"- [[{file}]]")
        else:
            lines.append("*No references yet*")
        lines.append("")
        return "\n".join(lines)

    def run(self, docs_dir: str = "docs", dry_run: bool = False, generate_cards: bool = True) -> Dict[str, Any]:
        print("\n" + "=" * 60)
        print("         TermCleaner - Domain Service")
        print("=" * 60)

        if dry_run:
            print("\n[Preview Mode] No files will be modified")

        files = self.scan_directory(docs_dir)

        files_modified = 0
        total_concepts = 0

        for filepath in files:
            if '/concepts/' in filepath or '/transformation/' in filepath:
                continue

            if dry_run:
                print(f"\n[Preview] {filepath}")
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()
                entities_found = self.find_entities_in_text(content)
                if entities_found:
                    print(f"   Would inject {len(entities_found)} concepts")
            else:
                modified, changes = self.process_file(filepath)
                if modified:
                    files_modified += 1
                    total_concepts += len([c for c in changes if c.startswith("Add concept")])

        cards_generated = 0
        if generate_cards and not dry_run:
            concepts_dir = self.settings.get('concepts_dir', 'docs/concepts')
            cards_generated = self.generate_concept_cards(concepts_dir)

        print(f"\n{'=' * 60}")
        print("                 Cleaning Complete")
        print(f"{'=' * 60}")
        print(f"  Files processed: {len(files)}")
        print(f"  Files modified:  {files_modified}")
        print(f"  Concepts injected: {total_concepts}")
        print(f"  Concept cards: {cards_generated}")

        return {
            "files_processed": len(files),
            "files_modified": files_modified,
            "concepts_injected": total_concepts,
            "cards_generated": cards_generated
        }


class CleaningService(BaseService):
    """Service for cleaning and pre-processing mined terminology."""

    def __init__(self, api_config: ApiConfig, scripts_dir: Path, timeout: int = 120):
        super().__init__(api_config)
        self._script_name = "clean_terms.py"
        self.scripts_dir = scripts_dir
        self.timeout = timeout

    def execute(self, **kwargs) -> Dict[str, Any]:
        self._logger.info("Starting terminology cleaning")

        try:
            result = self._run_cleaning_script(**kwargs)

            if result.returncode == 0:
                self._logger.info("Cleaning completed successfully")
                return {"success": True, "message": "Terminology cleaning completed"}
            else:
                error_msg = result.stderr or "Unknown error during cleaning"
                self._logger.error(f"Cleaning failed: {error_msg}")
                return {"success": False, "error": error_msg}

        except subprocess.TimeoutExpired as e:
            self._logger.error(f"Cleaning timed out: {e}")
            return {"success": False, "error": f"Timeout expired: {e}"}
        except FileNotFoundError as e:
            self._logger.error(f"Script not found: {e}")
            return {"success": False, "error": f"Script not found: {e}"}
        except (FileNotFoundError, PermissionError, OSError) as e:
            self._logger.error(f"OS error during cleaning: {e}")
            return {"success": False, "error": f"File system error: {e}"}
        except (ValueError, TypeError, KeyError) as e:
            self._logger.exception("Cleaning failed: invalid data")
            return {"success": False, "error": f"Invalid data: {e}"}

    def _run_cleaning_script(self, **kwargs) -> subprocess.CompletedProcess:
        script_path = self.scripts_dir / self._script_name

        cmd = [sys.executable, str(script_path)]

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

    def validate(self, **kwargs) -> bool:
        return True

    def get_cleaned_terms(self) -> List[Dict[str, Any]]:
        cleaned_file = self.scripts_dir.parent / "term_candidates_cleaned.yaml"

        if not cleaned_file.exists():
            return []

        try:
            with open(cleaned_file, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
                return data.get("terms", []) if data else []
        except yaml.YAMLError as e:
            self._logger.warning(f"Failed to parse cleaned terms (invalid YAML): {e}")
            return []
        except OSError as e:
            self._logger.warning(f"Failed to read cleaned terms: {e}")
            return []
