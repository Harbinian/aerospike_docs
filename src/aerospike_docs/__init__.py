"""aerospike_docs — Aerospace document governance SDK."""

__version__ = "0.1.0"

from .base import BaseService, ServiceError, ScriptNotFoundError, ServiceTimeoutError
from .core.config import ApiConfig, ConversionConfig, DomainConfig, MINIMAX_MODEL_NAME
from .core.schemas import ServiceResponse
from .core.exceptions import DocOpsError, ValidationError
from .core.logging import get_logger, setup_logging
