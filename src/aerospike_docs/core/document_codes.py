"""Load private document prefixes without embedding organization-specific values."""
import json
import os
from pathlib import Path
import re

PUBLIC_PREFIXES = {
    "policy": "POL",
    "procedure": "PROC",
    "instruction": "WORK",
    "form": "FORM",
    "standard": "SR",
}


def load_doc_prefixes(project_root=None):
    """Use an optional ignored local profile; absent profiles use public examples."""
    configured = os.environ.get("AEROSPIKE_DOC_PROFILE")
    path = Path(configured) if configured else Path(project_root or Path.cwd()) / "ANONYMIZATION.local.json"
    result = PUBLIC_PREFIXES.copy()
    if not path.exists():
        if configured:
            raise ValueError("The configured private document profile is unavailable.")
        return result
    try:
        aliases = json.loads(path.read_text(encoding="utf-8")).get("prefix_aliases", {})
        if not isinstance(aliases, dict):
            raise ValueError()
        used = set()
        for source, public in aliases.items():
            if not isinstance(source, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", source):
                raise ValueError()
            for category, prefix in PUBLIC_PREFIXES.items():
                if public == prefix:
                    if category in used:
                        raise ValueError()
                    result[category] = source.upper()
                    used.add(category)
        if len({value.casefold() for value in result.values()}) != len(result):
            raise ValueError()
    except (OSError, ValueError, TypeError, AttributeError):
        raise ValueError("The private document profile is invalid.") from None
    return result


def code_patterns(prefixes=None):
    """Build patterns from the active profile while preserving numeric formats."""
    values = prefixes or PUBLIC_PREFIXES
    suffixes = {
        "policy": r"\s*(\d{4})",
        "procedure": r"\s*(\d{4,6})",
        "instruction": r"\s*(\d{4}\d*-?\d*)",
        "form": r"\s*(\d{4}-\d+)",
        "standard": r"\s*(\d{4})",
    }
    return {values[key]: re.escape(values[key]) + suffix for key, suffix in suffixes.items()}


def form_id_patterns(prefixes=None):
    """Build linter rules directly, avoiding substitutions inside other aliases."""
    values = prefixes or PUBLIC_PREFIXES
    document_types = "|".join(re.escape(values[key]) for key in ("policy", "procedure", "instruction"))
    return [
        r"\b(" + re.escape(values["form"]) + r"\s*\d{4}[-\s]?\d{2}[A-Z]?)\b",
        r"\b((?:" + document_types + r")\d{4,6}[-\d]*)\b",
        r"\b(" + re.escape(values["standard"]) + r"\d{4}[A-Z]?)\b",
    ]
