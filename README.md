# aerospike_docs

Aerospace document governance SDK — terminology mining, knowledge graphs, RAG retrieval, and compliance auditing.

**Version:** 0.1.0 | **Python:** >= 3.12 | **License:** MIT

---

## Features

| Module | Capability |
|--------|-----------|
| `aerospike_docs.conversion` | DOCX/PDF/Excel → Markdown with YAML frontmatter, WikiLinks, image extraction |
| `aerospike_docs.governance` | LLM-powered term mining, cleaning, promotion, compliance auditing |
| `aerospike_docs.knowledge` | Knowledge graph construction and analysis |
| `aerospike_docs.retrieval` | RAG pipeline: chunking, embedding (MiniMax), ChromaDB vector search, QA engine |
| `aerospike_docs.export` | Data validation and export to system/master formats |
| `aerospike_docs.validation` | Glossary YAML structural integrity checking |
| `aerospike_docs.ui` | Script runner, pipeline orchestration, data loaders for Streamlit UIs |
| `aerospike_docs.core` | Config, logging, exceptions, schemas, utilities |

---

## Install

```bash
pip install -e /path/to/aerospike_docs
```

Or from the project root:

```bash
cd E:\CA001\aerospike_docs
pip install -e .
```

### Dependencies

Core: `pydantic>=2`, `pyyaml>=6`, `chromadb>=0.5`, `requests>=2`, `pandas>=2`, `python-docx>=1`, `pdfplumber>=0.10`, `openpyxl>=3.1`, `xlrd>=2`

---

## Quick Start

### 1. Configure API credentials

```python
import os
os.environ["MINIMAX_API_KEY"] = "your-jwt-token"
os.environ["MINIMAX_MODEL_NAME"] = "MiniMax-M2.7"
os.environ["MINIMAX_EMBEDDING_MODEL"] = "embo-01"
```

### 2. Convert documents

```python
from aerospike_docs.conversion import PipelineConverter

converter = PipelineConverter()
result = converter.convert_file("POL1407_工装工具管理.docx", "./outputs")
print(f"Success: {result.success}")
```

### 3. Mine terminology

```python
from aerospike_docs.core.config import ApiConfig
from aerospike_docs.governance import TermMiner

config = ApiConfig()
miner = TermMiner(config, docs_dir="./outputs")
result = miner.mine()
```

### 4. Validate glossary

```python
from aerospike_docs.validation import GlossaryValidator

validator = GlossaryValidator("glossary.yaml")
validator.load_file()
result = validator.validate()
print(f"Passed: {result.passed}, Errors: {len(result.errors)}")
```

### 5. RAG retrieval

```python
from aerospike_docs.retrieval import MarkdownChunker, MinimaxEmbedder, ChromaManager

chunker = MarkdownChunker()
embedder = MinimaxEmbedder()
vector_store = ChromaManager(collection_name="my_docs")

chunks = chunker.chunk_directory("./outputs")
embeddings = embedder.embed([c.content for c in chunks])
vector_store.add_documents(
    documents=[c.content for c in chunks],
    embeddings=embeddings,
    metadatas=[c.metadata for c in chunks]
)
```

### 6. File I/O with DataService

```python
from pathlib import Path
from aerospike_docs import DataService

ds = DataService(project_root=Path("./my_project"))
glossary = ds.load_glossary()
terms_df = ds.load_terms_candidates()
graph_html = ds.load_knowledge_graph()
```

---

## Architecture

```
aerospike_docs/
├── base.py              # BaseService, ServiceError
├── data_service.py      # File I/O abstraction
├── core/
│   ├── config.py        # ApiConfig, ConversionConfig, DomainConfig
│   ├── exceptions.py    # DocOpsError, ValidationError, ...
│   ├── logging.py       # Structured logging
│   ├── schemas.py       # ServiceResponse
│   └── utils.py         # clean_text, write_file_with_utf8
├── conversion/
│   ├── parser.py        # DOCX/PDF/Excel → DocumentElement
│   ├── converter.py     # PipelineConverter, MarkdownConverter
│   ├── linter.py        # Markdown quality checks
│   ├── auditor.py       # Conversion auditing
│   └── ai_cleaner.py    # LLM-based doc cleaning
├── governance/
│   ├── miner.py         # LLM term discovery
│   ├── cleaner.py       # Pre-clean noise
│   ├── promoter.py      # Merge to glossary
│   ├── auditor.py       # Compliance auditing
│   └── org_auditor.py   # Organization structure audit
├── knowledge/
│   ├── builder.py       # Graph construction
│   └── analyzer.py      # Coverage analysis
├── retrieval/
│   ├── chunker.py       # Markdown chunking
│   ├── embedder.py      # MiniMax embeddings
│   ├── vector_store.py  # ChromaDB management
│   └── qa_engine.py     # RAG + GraphRAG
├── export/
│   ├── exporter.py      # Data export
│   └── validator.py     # Pre-export validation
├── validation/
│   └── validator.py     # Glossary YAML validator
└── ui/
    ├── data_loaders.py  # Convenience loaders
    ├── pipelines.py     # Workflow orchestration
    └── script_runner.py # Secure subprocess runner
```

---

## Integrating with an existing project

If you are migrating from a monorepo that already has `services/` and `core/` packages, use the backward-compatible shim pattern:

```python
# services/conversion/__init__.py (shim)
from aerospike_docs.conversion import (
    PipelineConverter, MarkdownConverter, ConversionService,
    ConvertResult, create_parser
)
__all__ = ["PipelineConverter", "MarkdownConverter", ...]
```

This allows existing `from services.conversion import PipelineConverter` imports to keep working while the canonical implementation lives in `aerospike_docs`.

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `MINIMAX_API_KEY` | For LLM features | — | JWT token for MiniMax API |
| `MINIMAX_API_URL` | No | `https://api.minimax.chat/v1/text/chatcompletion_v2` | API endpoint |
| `MINIMAX_MODEL_NAME` | For LLM features | — | e.g. `MiniMax-M2.7` |
| `MINIMAX_EMBEDDING_MODEL` | For RAG | — | e.g. `embo-01` |
| `CHROMA_DB_DIR` | No | `./data/chroma_db` | Vector DB path |

---

## Development

```bash
# Install in editable mode
pip install -e .

# Run package tests
python -m pytest tests -q
```

---

*(Chinese Translation / 中文参考)*

# aerospike_docs — 航空航天文档治理 SDK

## 功能模块

| 模块 | 能力 |
|------|------|
| `conversion` | DOCX/PDF/Excel 转 Markdown，含 YAML 前置元数据、WikiLinks、图片提取 |
| `governance` | 基于大模型的术语挖掘、清洗、入库、合规审计 |
| `knowledge` | 知识图谱构建与分析 |
| `retrieval` | RAG 管线：文档切块、向量嵌入（MiniMax）、ChromaDB 向量检索、问答引擎 |
| `export` | 数据校验与导出（系统初始化格式/树形主数据格式） |
| `validation` | 术语表 YAML 结构完整性校验 |
| `ui` | 脚本运行器、管线编排、Streamlit UI 数据加载器 |
| `core` | 配置、日志、异常、数据模型、工具函数 |

## 安装

```bash
pip install -e /path/to/aerospike_docs
```

## 快速开始

1. 配置 API 密钥（环境变量 `MINIMAX_API_KEY`、`MINIMAX_MODEL_NAME`）
2. 使用 `PipelineConverter` 转换文档
3. 使用 `TermMiner` 挖掘术语
4. 使用 `GlossaryValidator` 校验术语表
5. 使用 `ChromaManager` 进行向量检索

## 环境变量

| 变量 | 必须 | 默认值 | 说明 |
|------|------|--------|------|
| `MINIMAX_API_KEY` | LLM功能需要 | — | MiniMax API JWT令牌 |
| `MINIMAX_MODEL_NAME` | LLM功能需要 | — | 模型名称，如 `MiniMax-M2.7` |
| `MINIMAX_EMBEDDING_MODEL` | RAG需要 | — | 嵌入模型，如 `embo-01` |

## 与现有项目集成

如果从包含 `services/` 和 `core/` 包的单体仓库迁移，使用向后兼容的 shim 模式：

```python
# services/conversion/__init__.py (shim)
from aerospike_docs.conversion import PipelineConverter
```

这样现有的 `from services.conversion import PipelineConverter` 导入方式继续有效，而规范实现位于 `aerospike_docs` 库中。
