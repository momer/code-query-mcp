"""Application layer for documentation workflows.

This module provides high-level orchestration for documentation workflows,
including file discovery, analysis, and batch processing.
"""

from .documentation_service import DocumentationService
from .file_discovery import FileDiscoveryService
from .file_analyzer import FileAnalyzer, FileAnalyzerRegistry
from .documentation_models import (
    DocumentationRequest,
    DocumentationResult,
    DocumentationStatus,
    FileType,
    FileAnalysisResult,
    ProgressUpdate
)
from .progress_tracker import ProgressTracker

__all__ = [
    'DocumentationService',
    'FileDiscoveryService',
    'FileAnalyzer',
    'FileAnalyzerRegistry',
    'DocumentationRequest',
    'DocumentationResult',
    'DocumentationStatus',
    'FileType',
    'FileAnalysisResult',
    'ProgressUpdate',
    'ProgressTracker'
]