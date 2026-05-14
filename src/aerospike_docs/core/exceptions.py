# -*- coding: utf-8 -*-
"""Custom exception classes for DocOps platform."""

from typing import Optional, Any


class DocOpsError(Exception):
    """Base exception class for all DocOps errors."""

    def __init__(self, message: str, cause: Optional[Exception] = None):
        self.message = message
        self.cause = cause
        super().__init__(self.message)
        if self.cause:
            self.__cause__ = cause

    def __str__(self) -> str:
        if self.cause:
            return f"{self.message} (caused by: {self.cause})"
        return self.message


class ValidationError(DocOpsError):
    """Raised when data validation fails."""

    def __init__(self, message: str, cause: Optional[Exception] = None):
        super().__init__(message, cause)


class ConversionError(DocOpsError):
    """Raised when document conversion fails."""

    def __init__(self, message: str, cause: Optional[Exception] = None):
        super().__init__(message, cause)


class MiningError(DocOpsError):
    """Raised when term mining operation fails."""

    def __init__(self, message: str, cause: Optional[Exception] = None):
        super().__init__(message, cause)


class ExportError(DocOpsError):
    """Raised when data export operation fails."""

    def __init__(self, message: str, cause: Optional[Exception] = None):
        super().__init__(message, cause)


class ConfigurationError(DocOpsError):
    """Raised when configuration is invalid or missing."""

    def __init__(self, message: str, cause: Optional[Exception] = None):
        super().__init__(message, cause)


class FileOperationError(DocOpsError):
    """Raised when file operations fail."""

    def __init__(self, message: str, cause: Optional[Exception] = None):
        super().__init__(message, cause)


class GlossaryError(DocOpsError):
    """Raised when glossary operations fail."""

    def __init__(self, message: str, cause: Optional[Exception] = None):
        super().__init__(message, cause)
