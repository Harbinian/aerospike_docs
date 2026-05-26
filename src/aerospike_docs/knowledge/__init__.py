"""aerospike_docs.knowledge sub-package."""

from .builder import GraphBuilder
from .analyzer import KnowledgeAnalyzer

KnowledgeGraphBuilder = GraphBuilder
KnowledgeGraphAnalyzer = KnowledgeAnalyzer

__all__ = [
    "GraphBuilder",
    "KnowledgeAnalyzer",
    "KnowledgeGraphBuilder",
    "KnowledgeGraphAnalyzer",
]
