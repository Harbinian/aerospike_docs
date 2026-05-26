# -*- coding: utf-8 -*-
"""Migration-facing public API tests."""

from pathlib import Path

from aerospike_docs.core.config import ApiConfig
from aerospike_docs.export import DataExporter
from aerospike_docs.governance import TermMiner
from aerospike_docs.retrieval import MinimaxEmbedder


def test_data_exporter_rejects_invalid_glossary_without_norms_services(tmp_path: Path):
    glossary = tmp_path / "glossary.yaml"
    glossary.write_text(
        """
entities:
  - id: Root
    name: Root
    category: 工装类型
    is_root: true
  - id: Child_Tooling
    name: Child
    category: 工装类型
    parent: MissingParent
""".strip(),
        encoding="utf-8",
    )

    assert DataExporter(project_root=tmp_path).validate_glossary() is False


def test_embedder_exposes_readme_embed_alias(monkeypatch):
    config = ApiConfig(
        minimax_api_key="key",
        minimax_model_name="chat-model",
        minimax_embedding_model="embedding-model",
    )
    embedder = MinimaxEmbedder(config)

    def fake_embed_texts(texts, embed_type="db"):
        return [[float(len(text))] for text in texts]

    monkeypatch.setattr(embedder, "embed_texts", fake_embed_texts)

    assert embedder.embed(["alpha", "beta"]) == [[5.0], [4.0]]


def test_term_miner_accepts_api_config_as_first_argument():
    config = ApiConfig(
        minimax_api_key="key",
        minimax_model_name="chat-model",
        minimax_embedding_model="embedding-model",
    )

    miner = TermMiner(config)

    assert miner.api_config is config
    assert miner.docs_dir == Path("docs")


def test_knowledge_exports_backward_compatible_names():
    from aerospike_docs.knowledge import (
        GraphBuilder,
        KnowledgeAnalyzer,
        KnowledgeGraphAnalyzer,
        KnowledgeGraphBuilder,
    )

    assert KnowledgeGraphBuilder is GraphBuilder
    assert KnowledgeGraphAnalyzer is KnowledgeAnalyzer
