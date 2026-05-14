# -*- coding: utf-8 -*-
"""Pipeline orchestration for common UI workflows."""

from pathlib import Path

from aerospike_docs.ui.script_runner import run_script
from aerospike_docs.core.logging import get_logger

logger = get_logger(__name__)


def build_knowledge_graph(scripts_dir: Path, timeout: int = 300) -> bool:
    """Build knowledge graph: map_knowledge.py -> visualize_graph.py."""
    success1, _, err1 = run_script('map_knowledge.py', scripts_dir, timeout=timeout)
    if not success1:
        logger.error(f"map_knowledge.py failed: {err1}")
        return False
    success2, _, err2 = run_script('visualize_graph.py', scripts_dir, timeout=timeout)
    if not success2:
        logger.error(f"visualize_graph.py failed: {err2}")
        return False
    return True


def run_compliance_audit(scripts_dir: Path, timeout: int = 300) -> bool:
    """Run full compliance audit pipeline."""
    success, _, err = run_script('audit_actors.py', scripts_dir, timeout=timeout)
    if not success:
        logger.error(f"audit_actors.py failed: {err}")
    return success


def run_ontology_build(scripts_dir: Path, timeout: int = 300) -> bool:
    """Build CUSTOMER_A ontology."""
    success, _, err = run_script('ontology_builder.py', scripts_dir, timeout=timeout)
    if not success:
        logger.error(f"ontology_builder.py failed: {err}")
    return success
