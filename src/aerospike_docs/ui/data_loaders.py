# -*- coding: utf-8 -*-
"""UI data loader utilities — thin re-exports from DataService."""

from pathlib import Path
from typing import Dict, Any

import pandas as pd

from aerospike_docs.data_service import DataService
from aerospike_docs.core.logging import get_logger

logger = get_logger(__name__)


def load_glossary(data_service: DataService) -> Dict[str, Any]:
    """Load glossary. Convenience wrapper for UI compatibility."""
    return data_service.load_glossary()


def load_csv(data_service: DataService, filepath: Path) -> pd.DataFrame:
    """Load CSV. Convenience wrapper for UI compatibility."""
    return data_service.load_csv(filepath)
