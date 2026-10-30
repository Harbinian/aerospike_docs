"""Document profiles preserve private numbering without publishing private names."""
import json
from pathlib import Path
import re

import pytest

from aerospike_docs.core.document_codes import code_patterns, load_doc_prefixes
from aerospike_docs.conversion.linter import MarkdownLinter
from aerospike_docs.knowledge.builder import GraphBuilder


def builder(tmp_path):
    (tmp_path / "refined_outputs").mkdir(exist_ok=True)
    return GraphBuilder(project_root=tmp_path)


def private_profile(tmp_path):
    path = tmp_path / "ANONYMIZATION.local.json"
    path.write_text(json.dumps({"prefix_aliases": {
        "PX": "POL", "QX": "PROC", "RX": "WORK", "TX": "FORM",
    }}), encoding="utf-8")
    return path


def test_public_examples_parse_and_link_without_private_configuration(tmp_path, monkeypatch):
    monkeypatch.delenv("AEROSPIKE_DOC_PROFILE", raising=False)
    service = builder(tmp_path)
    assert [service.infer_doc_level(value) for value in (
        "POL1407", "PROC140701", "WORK140701", "FORM1407-01",
    )] == [0, 1, 2, 3]
    assert service.parse_doc_code("PROC140701_example") == "PROC140701"
    assert service.find_best_parent_by_code("WORK140701", {"PROC140701"}) == "PROC140701"
    assert service.find_best_parent_by_code("PROC140701", {"POL1407"}) == "POL1407"


def test_private_profile_preserves_original_identifiers_and_parent_links(tmp_path, monkeypatch):
    monkeypatch.delenv("AEROSPIKE_DOC_PROFILE", raising=False)
    private_profile(tmp_path)
    service = builder(tmp_path)
    assert service.parse_doc_code("QX140701_example") == "QX140701"
    assert service.infer_doc_level("TX1407-01") == 3
    assert service.find_best_parent_by_code("RX140701", {"QX140701"}) == "QX140701"
    assert service.find_best_parent_by_code("QX140701", {"PX1407"}) == "PX1407"
    patterns = code_patterns(service.doc_prefixes)
    assert re.findall(patterns["TX"], "TX1407-01") == ["1407-01"]


def test_linter_uses_private_form_prefix(tmp_path, monkeypatch):
    monkeypatch.delenv("AEROSPIKE_DOC_PROFILE", raising=False)
    private_profile(tmp_path)
    service = MarkdownLinter(project_root=tmp_path)
    assert any(re.search(pattern, "TX1407-01") for pattern in service.form_patterns)
    assert any(re.search(pattern, "QX140701") for pattern in service.form_patterns)


@pytest.mark.parametrize("private", [False, True])
def test_citations_and_form_references_use_the_same_profile(tmp_path, monkeypatch, private):
    monkeypatch.delenv("AEROSPIKE_DOC_PROFILE", raising=False)
    if private:
        private_profile(tmp_path)
    service = builder(tmp_path)
    policy = service.doc_prefixes["policy"]
    procedure = service.doc_prefixes["procedure"]
    form = service.doc_prefixes["form"]
    content = f"1 规范性引用文件\n{policy}1407\n{procedure}140701\n2 表格\n{form}1407-01\n"
    assert service.extract_official_references(content) == {
        "cites": [policy + "1407", procedure + "140701"],
        "forms": [form + "1407-01"],
    }


def test_missing_explicit_profile_is_an_error(tmp_path, monkeypatch):
    monkeypatch.setenv("AEROSPIKE_DOC_PROFILE", str(tmp_path / "missing.json"))
    with pytest.raises(ValueError, match="unavailable"):
        load_doc_prefixes(tmp_path)


def test_invalid_profile_does_not_silently_use_public_defaults(tmp_path, monkeypatch):
    monkeypatch.delenv("AEROSPIKE_DOC_PROFILE", raising=False)
    (tmp_path / "ANONYMIZATION.local.json").write_text('{"prefix_aliases": []}', encoding="utf-8")
    with pytest.raises(ValueError, match="invalid"):
        load_doc_prefixes(tmp_path)
