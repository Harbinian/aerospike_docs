# -*- coding: utf-8 -*-
"""Base service class for aerospike_docs."""

from abc import ABC, abstractmethod
from typing import Any, Callable, Optional, Dict, List, TypeVar, Generic

from aerospike_docs.core.config import ApiConfig
from aerospike_docs.core.logging import get_logger
from aerospike_docs.core.exceptions import ValidationError, DocOpsError

T = TypeVar("T")


class ServiceError(DocOpsError):
    """Base exception for service-related errors."""
    pass


class ScriptNotFoundError(ServiceError):
    """Raised when a required script is not found."""
    pass


class ServiceTimeoutError(ServiceError):
    """Raised when a service operation times out."""
    pass


class BaseService(ABC):
    """Abstract base class for all services."""

    def __init__(self, api_config: ApiConfig):
        self.api_config = api_config
        self._logger = get_logger(self.__class__.__name__)

    @property
    def logger(self):
        return self._logger

    @abstractmethod
    def execute(self, *args, **kwargs) -> Any:
        pass

    def _run_with_error_handling(
        self, func: Callable[..., T], *args,
        error_message: str = "Operation failed", **kwargs
    ) -> T:
        func_name = getattr(func, '__name__', repr(func))
        try:
            self._logger.debug(f"Executing {func_name}")
            result = func(*args, **kwargs)
            self._logger.debug(f"Completed {func_name}")
            return result
        except (ValidationError, DocOpsError):
            raise
        except KeyError as e:
            self._logger.error(f"{error_message}: Missing key {e}", exc_info=True)
            raise ServiceError(f"{error_message}: Missing key {e}")
        except TypeError as e:
            self._logger.error(f"{error_message}: Invalid argument {e}", exc_info=True)
            raise ServiceError(f"{error_message}: Invalid argument {e}")
        except ValueError as e:
            self._logger.error(f"{error_message}: Invalid value {e}", exc_info=True)
            raise ServiceError(f"{error_message}: Invalid value {e}")
        except (FileNotFoundError, PermissionError, OSError) as e:
            self._logger.error(f"{error_message}: File system error {e}", exc_info=True)
            raise DocOpsError(f"{error_message}: File system error {e}", cause=e)

    def _run_with_progress(
        self, func: Callable[..., T],
        progress_callback: Optional[Callable[[int, str], None]] = None,
        *args, **kwargs
    ) -> T:
        if progress_callback:
            progress_callback(0, "Starting operation...")
        try:
            result = func(*args, **kwargs)
            if progress_callback:
                progress_callback(100, "Operation completed")
            return result
        except Exception as e:
            if progress_callback:
                progress_callback(0, f"Operation failed: {e}")
            raise

    def _validate_params(self, params: Dict[str, Any], required: List[str]) -> None:
        missing = [key for key in required if key not in params or params[key] is None]
        if missing:
            error_msg = f"Missing required parameters: {', '.join(missing)}"
            self._logger.error(error_msg)
            raise ValidationError(error_msg)

    def _validate_types(self, params: Dict[str, Any], type_map: Dict[str, type]) -> None:
        for key, expected_type in type_map.items():
            if key in params and params[key] is not None:
                if not isinstance(params[key], expected_type):
                    actual_type = type(params[key]).__name__
                    expected_name = expected_type.__name__
                    error_msg = f"Invalid type for '{key}': expected {expected_name}, got {actual_type}"
                    self._logger.error(error_msg)
                    raise ValidationError(error_msg)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}()"
