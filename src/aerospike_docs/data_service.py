# -*- coding: utf-8 -*-
"""Data Service - domain service for file I/O operations."""

import json
from pathlib import Path
from typing import Dict, List, Any, Optional

import pandas as pd
import yaml

from aerospike_docs.core.logging import get_logger

logger = get_logger(__name__)


class DataService:
    """Encapsulates all file I/O operations."""

    def __init__(self, project_root: Path, glossary_file: Optional[Path] = None):
        self.project_root = project_root
        self.glossary_file = glossary_file or (project_root / "glossary.yaml")
        self.outputs_dir = project_root / "outputs"
        self.dist_dir = project_root / "dist"

    # CSV
    def load_csv(self, filepath: Path) -> pd.DataFrame:
        try:
            return pd.read_csv(filepath, encoding='utf-8-sig')
        except FileNotFoundError:
            logger.warning(f"CSV file not found: {filepath}")
            return pd.DataFrame()
        except Exception as e:
            logger.error(f"Failed to load CSV file {filepath}: {e}")
            return pd.DataFrame()

    def save_csv(self, df: pd.DataFrame, filepath: Path) -> bool:
        try:
            df.to_csv(filepath, index=False, encoding='utf-8-sig')
            return True
        except Exception as e:
            logger.error(f"Failed to save CSV file {filepath}: {e}")
            return False

    def load_conversion_report(self) -> pd.DataFrame:
        return self.load_csv(self.project_root / 'conversion_audit.csv')

    def load_terms_candidates(self) -> pd.DataFrame:
        return self.load_csv(self.project_root / 'term_candidates.csv')

    def load_alias_suggestions(self) -> pd.DataFrame:
        return self.load_csv(self.dist_dir / 'alias_suggestions.csv')

    def save_terms_candidates(self, df: pd.DataFrame) -> bool:
        return self.save_csv(df, self.project_root / 'term_candidates.csv')

    # YAML
    def load_yaml(self, filepath: Path) -> Dict[str, Any]:
        if not filepath or not filepath.exists():
            logger.warning(f"YAML file not found: {filepath}")
            return {}
        try:
            with open(filepath, encoding='utf-8') as f:
                data = yaml.safe_load(f)
                return data if data else {}
        except Exception as e:
            logger.error(f"Failed to load YAML file {filepath}: {e}")
            return {}

    def save_yaml(self, data: Dict[str, Any], filepath: Path) -> bool:
        try:
            filepath.parent.mkdir(parents=True, exist_ok=True)
            with open(filepath, 'w', encoding='utf-8') as f:
                yaml.dump(data, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
            return True
        except Exception as e:
            logger.error(f"Failed to save YAML file {filepath}: {e}")
            return False

    def load_glossary(self) -> Dict[str, Any]:
        return self.load_yaml(self.glossary_file)

    def save_glossary(self, data: Dict[str, Any]) -> bool:
        return self.save_yaml(data, self.glossary_file)

    # JSON
    def load_json(self, filepath: Path) -> Dict[str, Any]:
        if not filepath or not filepath.exists():
            logger.warning(f"JSON file not found: {filepath}")
            return {}
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load JSON file {filepath}: {e}")
            return {}

    def load_orphan_report(self) -> Dict[str, Any]:
        return self.load_json(self.dist_dir / 'check_orphans.json')

    # Markdown
    def load_markdown(self, filepath: Path) -> str:
        if not filepath or not filepath.exists():
            logger.warning(f"Markdown file not found: {filepath}")
            return ""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            logger.error(f"Failed to load markdown file {filepath}: {e}")
            return ""

    def load_compliance_audit(self) -> str:
        return self.load_markdown(self.dist_dir / 'compliance_actor_audit.md')

    def load_lifecycle_audit(self) -> str:
        return self.load_markdown(self.dist_dir / 'reports' / 'lifecycle_elements_audit.md')

    def load_sql_lineage(self) -> str:
        return self.load_markdown(self.dist_dir / 'reports' / 'sql_lineage_report.md')

    # HTML
    def load_html(self, filepath: Path) -> str:
        if not filepath or not filepath.exists():
            logger.warning(f"HTML file not found: {filepath}")
            return ""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            logger.error(f"Failed to load HTML file {filepath}: {e}")
            return ""

    def load_knowledge_graph(self) -> str:
        return self.load_html(self.project_root / 'knowledge_graph.html')

    # Checks
    def file_exists(self, filepath: Path) -> bool:
        return filepath and filepath.exists()

    def graph_exists(self) -> bool:
        return self.file_exists(self.project_root / 'knowledge_graph.html')

    def glossary_exists(self) -> bool:
        return self.file_exists(self.glossary_file)
