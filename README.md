# aerospike_docs

Aerospace document governance SDK.

## Install

```bash
pip install -e .
```

## Usage

```python
import os
os.environ["MINIMAX_API_KEY"] = "your-key"
os.environ["MINIMAX_MODEL_NAME"] = "MiniMax-M2.5"
os.environ["MINIMAX_EMBEDDING_MODEL"] = "embo-01"

from aerospike_docs.core.config import ApiConfig
from aerospike_docs.governance.miner import TermMiner

config = ApiConfig()
miner = TermMiner(config)
result = miner.mine(outputs_dir="/path/to/docs")
```

## Requirements

- Python >= 3.12
- Minimax API key for LLM features
