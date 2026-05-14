# -*- coding: utf-8 -*-
"""Unified DTO schemas for DocOps platform services."""

from dataclasses import dataclass, field
from typing import Any, Generic, Optional, TypeVar

T = TypeVar("T")


@dataclass
class ServiceResponse(Generic[T]):
    """
    Unified response object for all service operations.

    Attributes:
        success: Whether the operation succeeded
        data: The result data (optional)
        error_msg: Error message if operation failed (optional)
        metadata: Additional metadata about the operation (optional)
    """

    success: bool
    data: Optional[T] = None
    error_msg: str = ""
    metadata: dict = field(default_factory=dict)

    @classmethod
    def ok(cls, data: Optional[T] = None, metadata: Optional[dict] = None) -> "ServiceResponse[T]":
        """Create a successful response."""
        return cls(
            success=True,
            data=data,
            metadata=metadata or {}
        )

    @classmethod
    def fail(cls, error_msg: str, metadata: Optional[dict] = None) -> "ServiceResponse[T]":
        """Create a failed response."""
        return cls(
            success=False,
            error_msg=error_msg,
            metadata=metadata or {}
        )

    def __bool__(self) -> bool:
        """Allow using ServiceResponse in boolean context."""
        return self.success
