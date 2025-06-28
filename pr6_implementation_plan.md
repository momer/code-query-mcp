# PR 6: Application Layer for Documentation Workflows

## Overview
This PR creates an application layer that orchestrates file documentation workflows across domain boundaries. It provides high-level APIs for documenting entire directories, managing documentation lifecycles, and coordinating between the Dataset Service and Storage Backend.

**Size**: Small | **Risk**: Low | **Value**: Medium

## Dependencies
- PR 2 must be completed (needs StorageBackend interface)
- PR 5 must be completed (needs DatasetService)
- This PR blocks PR 7 (Analytics may need documentation metadata)

## Objectives
1. Create high-level documentation workflow orchestration
2. Implement efficient batch processing for large directories
3. Provide file analysis abstraction layer
4. Handle documentation updates and incremental indexing
5. Support various file types and analysis strategies

## Implementation Steps

### Step 1: Create Directory Structure
```
app/
├── __init__.py                    # Export main services
├── documentation_service.py       # Main documentation workflow orchestration
├── file_analyzer.py              # File analysis abstraction
├── file_discovery.py             # File discovery and filtering
├── documentation_models.py       # Application-level models
└── progress_tracker.py           # Progress tracking for long operations
```

### Step 2: Define Application Models
**File**: `app/documentation_models.py`
- DocumentationRequest models
- DocumentationResult models
- Progress tracking models
- File analysis results

### Step 3: Implement File Discovery
**File**: `app/file_discovery.py`
- Recursive directory traversal
- Pattern-based file filtering
- Git-aware file selection
- Incremental discovery support

### Step 4: Implement File Analyzer
**File**: `app/file_analyzer.py`
- Abstract interface for file analysis
- Language-specific analyzer registry
- Fallback analyzer for unknown types
- Parallel analysis support

### Step 5: Implement Documentation Service
**File**: `app/documentation_service.py`
- High-level documentation workflows
- Batch processing coordination
- Progress reporting
- Error handling and recovery

### Step 6: Add Progress Tracking
**File**: `app/progress_tracker.py`
- Real-time progress updates
- Cancellation support
- Progress persistence for resume
- ETA calculations

## Detailed Implementation

### app/documentation_models.py
```python
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Set
from datetime import datetime
from enum import Enum
from pathlib import Path

class DocumentationStatus(Enum):
    """Status of documentation operation."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class FileType(Enum):
    """Supported file types for analysis."""
    PYTHON = "python"
    JAVASCRIPT = "javascript"
    TYPESCRIPT = "typescript"
    JAVA = "java"
    CPP = "cpp"
    GO = "go"
    RUST = "rust"
    MARKDOWN = "markdown"
    UNKNOWN = "unknown"

@dataclass
class DocumentationRequest:
    """Request to document a directory or files."""
    dataset_name: str
    source_directory: str
    include_patterns: List[str] = field(default_factory=list)
    exclude_patterns: List[str] = field(default_factory=list)
    batch_size: int = 100
    update_existing: bool = True
    analyze_content: bool = True
    max_file_size: int = 10 * 1024 * 1024  # 10MB

@dataclass
class FileAnalysisResult:
    """Result of analyzing a single file."""
    filepath: str
    filename: str
    file_type: FileType
    overview: str
    ddd_context: Optional[str] = None
    functions: Optional[Dict[str, Any]] = None
    exports: Optional[Dict[str, Any]] = None
    imports: Optional[Dict[str, Any]] = None
    types_interfaces_classes: Optional[Dict[str, Any]] = None
    constants: Optional[Dict[str, Any]] = None
    dependencies: List[str] = field(default_factory=list)
    other_notes: List[str] = field(default_factory=list)
    analysis_time: float = 0.0
    error: Optional[str] = None

@dataclass
class DocumentationProgress:
    """Progress tracking for documentation operations."""
    total_files: int
    processed_files: int
    successful_files: int
    failed_files: int
    skipped_files: int
    start_time: datetime
    current_file: Optional[str] = None
    errors: List[Dict[str, str]] = field(default_factory=list)
    
    @property
    def completion_percentage(self) -> float:
        """Calculate completion percentage."""
        if self.total_files == 0:
            return 100.0
        return (self.processed_files / self.total_files) * 100
    
    @property
    def elapsed_time(self) -> float:
        """Get elapsed time in seconds."""
        return (datetime.now() - self.start_time).total_seconds()
    
    @property
    def estimated_time_remaining(self) -> Optional[float]:
        """Estimate remaining time in seconds."""
        if self.processed_files == 0:
            return None
        
        rate = self.processed_files / self.elapsed_time
        remaining_files = self.total_files - self.processed_files
        return remaining_files / rate if rate > 0 else None

@dataclass
class DocumentationResult:
    """Result of a documentation operation."""
    dataset_name: str
    source_directory: str
    total_files: int
    documented_files: int
    failed_files: int
    skipped_files: int
    elapsed_time: float
    status: DocumentationStatus
    errors: List[Dict[str, str]] = field(default_factory=list)
    
    @property
    def success_rate(self) -> float:
        """Calculate success rate."""
        if self.total_files == 0:
            return 100.0
        return (self.documented_files / self.total_files) * 100
```

### app/file_discovery.py
```python
import os
import fnmatch
from pathlib import Path
from typing import List, Set, Iterator, Optional
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from .documentation_models import FileType

logger = logging.getLogger(__name__)

class FileDiscovery:
    """Discovers files for documentation with pattern matching."""
    
    # Default patterns to exclude
    DEFAULT_EXCLUDE_PATTERNS = [
        '*.pyc', '__pycache__', '*.pyo',
        'node_modules', 'bower_components', 'jspm_packages',
        '.git', '.svn', '.hg', '.bzr',
        '.idea', '.vscode', '*.swp', '*.swo',
        'dist', 'build', 'target', 'out',
        '*.min.js', '*.min.css',
        '.DS_Store', 'Thumbs.db',
        '*.log', '*.tmp', '*.temp',
        '.env', '.env.*',
        'venv', 'virtualenv', '.virtualenv'
    ]
    
    # File extension to type mapping
    FILE_TYPE_MAPPING = {
        '.py': FileType.PYTHON,
        '.js': FileType.JAVASCRIPT,
        '.jsx': FileType.JAVASCRIPT,
        '.ts': FileType.TYPESCRIPT,
        '.tsx': FileType.TYPESCRIPT,
        '.java': FileType.JAVA,
        '.cpp': FileType.CPP,
        '.cc': FileType.CPP,
        '.cxx': FileType.CPP,
        '.h': FileType.CPP,
        '.hpp': FileType.CPP,
        '.go': FileType.GO,
        '.rs': FileType.RUST,
        '.md': FileType.MARKDOWN,
    }
    
    def __init__(self, 
                 include_patterns: Optional[List[str]] = None,
                 exclude_patterns: Optional[List[str]] = None,
                 follow_symlinks: bool = False,
                 max_file_size: int = 10 * 1024 * 1024):
        """
        Initialize file discovery.
        
        Args:
            include_patterns: Patterns to include (if None, include all)
            exclude_patterns: Patterns to exclude (in addition to defaults)
            follow_symlinks: Whether to follow symbolic links
            max_file_size: Maximum file size to consider (bytes)
        """
        self.include_patterns = include_patterns or ['*']
        self.exclude_patterns = self.DEFAULT_EXCLUDE_PATTERNS.copy()
        if exclude_patterns:
            self.exclude_patterns.extend(exclude_patterns)
        self.follow_symlinks = follow_symlinks
        self.max_file_size = max_file_size
    
    def discover_files(self, directory: str) -> List[str]:
        """
        Discover all files in directory matching patterns.
        
        Args:
            directory: Root directory to search
            
        Returns:
            List of file paths
        """
        discovered_files = []
        
        for filepath in self._walk_directory(directory):
            if self._should_include_file(filepath):
                discovered_files.append(filepath)
        
        return sorted(discovered_files)
    
    def discover_files_parallel(self, directory: str, max_workers: int = 4) -> List[str]:
        """
        Discover files using parallel directory traversal.
        
        Args:
            directory: Root directory to search
            max_workers: Number of parallel workers
            
        Returns:
            List of file paths
        """
        discovered_files = set()
        
        # Get top-level directories for parallel processing
        try:
            root_path = Path(directory)
            subdirs = [str(d) for d in root_path.iterdir() if d.is_dir()]
            if not subdirs:
                return self.discover_files(directory)
            
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {
                    executor.submit(self.discover_files, subdir): subdir 
                    for subdir in subdirs
                }
                
                # Also process files in root
                futures[executor.submit(self._discover_root_files, directory)] = directory
                
                for future in as_completed(futures):
                    try:
                        files = future.result()
                        discovered_files.update(files)
                    except Exception as e:
                        logger.error(f"Error discovering files in {futures[future]}: {e}")
            
        except Exception as e:
            logger.error(f"Error in parallel discovery: {e}")
            # Fallback to serial discovery
            return self.discover_files(directory)
        
        return sorted(list(discovered_files))
    
    def _discover_root_files(self, directory: str) -> List[str]:
        """Discover only files in root directory (not subdirectories)."""
        discovered_files = []
        
        try:
            for entry in os.scandir(directory):
                if entry.is_file() and self._should_include_file(entry.path):
                    discovered_files.append(entry.path)
        except Exception as e:
            logger.error(f"Error scanning root directory {directory}: {e}")
        
        return discovered_files
    
    def _walk_directory(self, directory: str) -> Iterator[str]:
        """Walk directory yielding file paths."""
        for root, dirs, files in os.walk(directory, followlinks=self.follow_symlinks):
            # Filter directories to avoid excluded paths
            dirs[:] = [d for d in dirs if not self._should_exclude_dir(os.path.join(root, d))]
            
            for filename in files:
                filepath = os.path.join(root, filename)
                yield filepath
    
    def _should_include_file(self, filepath: str) -> bool:
        """Check if file should be included."""
        # Check file size
        try:
            if os.path.getsize(filepath) > self.max_file_size:
                return False
        except OSError:
            return False
        
        # Check exclude patterns first
        if self._matches_patterns(filepath, self.exclude_patterns):
            return False
        
        # Check include patterns
        return self._matches_patterns(filepath, self.include_patterns)
    
    def _should_exclude_dir(self, dirpath: str) -> bool:
        """Check if directory should be excluded."""
        dirname = os.path.basename(dirpath)
        return any(fnmatch.fnmatch(dirname, pattern) for pattern in self.exclude_patterns)
    
    def _matches_patterns(self, filepath: str, patterns: List[str]) -> bool:
        """Check if filepath matches any pattern."""
        filename = os.path.basename(filepath)
        
        for pattern in patterns:
            # Check against full path or just filename
            if fnmatch.fnmatch(filepath, pattern) or fnmatch.fnmatch(filename, pattern):
                return True
        
        return False
    
    def get_file_type(self, filepath: str) -> FileType:
        """Determine file type from extension."""
        ext = Path(filepath).suffix.lower()
        return self.FILE_TYPE_MAPPING.get(ext, FileType.UNKNOWN)
    
    def filter_by_type(self, filepaths: List[str], file_types: Set[FileType]) -> List[str]:
        """Filter files by type."""
        return [f for f in filepaths if self.get_file_type(f) in file_types]
```

### app/file_analyzer.py
```python
from abc import ABC, abstractmethod
from typing import Dict, Type, Optional, Any
import logging
from pathlib import Path
import json
import ast
import re

from .documentation_models import FileAnalysisResult, FileType

logger = logging.getLogger(__name__)

class FileAnalyzer(ABC):
    """Abstract base class for file analyzers."""
    
    @abstractmethod
    def analyze(self, filepath: str) -> FileAnalysisResult:
        """Analyze a file and extract documentation."""
        pass
    
    @abstractmethod
    def can_analyze(self, filepath: str) -> bool:
        """Check if this analyzer can handle the file."""
        pass

class PythonAnalyzer(FileAnalyzer):
    """Analyzer for Python files."""
    
    def can_analyze(self, filepath: str) -> bool:
        return filepath.endswith('.py')
    
    def analyze(self, filepath: str) -> FileAnalysisResult:
        """Analyze Python file using AST."""
        result = FileAnalysisResult(
            filepath=filepath,
            filename=Path(filepath).name,
            file_type=FileType.PYTHON,
            overview="",
            functions={},
            imports={},
            types_interfaces_classes={},
            constants={}
        )
        
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            
            tree = ast.parse(content, filename=filepath)
            
            # Extract overview from module docstring
            result.overview = self._get_module_docstring(tree)
            
            # Extract imports
            result.imports = self._extract_imports(tree)
            
            # Extract functions
            result.functions = self._extract_functions(tree)
            
            # Extract classes
            result.types_interfaces_classes = self._extract_classes(tree)
            
            # Extract constants
            result.constants = self._extract_constants(tree)
            
            # Extract dependencies
            result.dependencies = list(result.imports.keys())
            
        except Exception as e:
            logger.error(f"Error analyzing Python file {filepath}: {e}")
            result.error = str(e)
        
        return result
    
    def _get_module_docstring(self, tree: ast.Module) -> str:
        """Extract module-level docstring."""
        if (tree.body and 
            isinstance(tree.body[0], ast.Expr) and 
            isinstance(tree.body[0].value, ast.Constant) and
            isinstance(tree.body[0].value.value, str)):
            return tree.body[0].value.value.strip()
        return "Python module"
    
    def _extract_imports(self, tree: ast.Module) -> Dict[str, Any]:
        """Extract import statements."""
        imports = {}
        
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports[alias.name] = {
                        'type': 'import',
                        'alias': alias.asname
                    }
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ''
                for alias in node.names:
                    full_name = f"{module}.{alias.name}" if module else alias.name
                    imports[full_name] = {
                        'type': 'from_import',
                        'module': module,
                        'name': alias.name,
                        'alias': alias.asname
                    }
        
        return imports
    
    def _extract_functions(self, tree: ast.Module) -> Dict[str, Any]:
        """Extract function definitions."""
        functions = {}
        
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                functions[node.name] = {
                    'name': node.name,
                    'args': [arg.arg for arg in node.args.args],
                    'returns': self._safe_unparse(node.returns) if node.returns else None,
                    'docstring': ast.get_docstring(node),
                    'decorators': [self._safe_unparse(d) for d in node.decorator_list],
                    'is_async': isinstance(node, ast.AsyncFunctionDef)
                }
        
        return functions
    
    def _extract_classes(self, tree: ast.Module) -> Dict[str, Any]:
        """Extract class definitions."""
        classes = {}
        
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                classes[node.name] = {
                    'name': node.name,
                    'bases': [self._safe_unparse(base) for base in node.bases],
                    'docstring': ast.get_docstring(node),
                    'methods': self._extract_class_methods(node),
                    'decorators': [self._safe_unparse(d) for d in node.decorator_list]
                }
        
        return classes
    
    def _extract_class_methods(self, class_node: ast.ClassDef) -> Dict[str, Any]:
        """Extract methods from a class."""
        methods = {}
        
        for node in class_node.body:
            if isinstance(node, ast.FunctionDef):
                methods[node.name] = {
                    'name': node.name,
                    'args': [arg.arg for arg in node.args.args],
                    'docstring': ast.get_docstring(node),
                    'is_async': isinstance(node, ast.AsyncFunctionDef)
                }
        
        return methods
    
    def _extract_constants(self, tree: ast.Module) -> Dict[str, Any]:
        """Extract module-level constants."""
        constants = {}
        
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id.isupper():
                        try:
                            value = ast.literal_eval(node.value)
                            constants[target.id] = {
                                'name': target.id,
                                'value': value,
                                'type': type(value).__name__
                            }
                        except:
                            # If literal_eval fails, store string representation
                            constants[target.id] = {
                                'name': target.id,
                                'value': self._safe_unparse(node.value),
                                'type': 'expression'
                            }
        
        return constants
    
    def _safe_unparse(self, node) -> str:
        """Safely unparse AST node with Python version compatibility."""
        try:
            if hasattr(ast, 'unparse'):
                return ast.unparse(node)
            else:
                # Fallback for Python < 3.9
                return "<AST unparsing requires Python 3.9+>"
        except:
            return "<unparsing failed>"

class JavaScriptAnalyzer(FileAnalyzer):
    """Basic analyzer for JavaScript files."""
    
    def can_analyze(self, filepath: str) -> bool:
        return filepath.endswith(('.js', '.jsx'))
    
    def analyze(self, filepath: str) -> FileAnalysisResult:
        """Basic JavaScript analysis using regex."""
        result = FileAnalysisResult(
            filepath=filepath,
            filename=Path(filepath).name,
            file_type=FileType.JAVASCRIPT,
            overview="JavaScript module",
            functions={},
            imports={},
            exports={}
        )
        
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Extract imports (basic regex approach)
            import_pattern = r'import\s+(?:{[^}]+}|[\w\s,]+)\s+from\s+[\'"]([^\'\"]+)[\'"]'
            imports = re.findall(import_pattern, content)
            result.imports = {imp: {'module': imp} for imp in imports}
            
            # Extract function declarations
            func_pattern = r'(?:function\s+(\w+)|const\s+(\w+)\s*=\s*(?:async\s+)?(?:\([^)]*\)|[\w\s]*)\s*=>)'
            functions = re.findall(func_pattern, content)
            result.functions = {
                (f[0] or f[1]): {'name': f[0] or f[1]} 
                for f in functions if f[0] or f[1]
            }
            
            # Extract exports
            export_pattern = r'export\s+(?:default\s+)?(?:function\s+)?(\w+)'
            exports = re.findall(export_pattern, content)
            result.exports = {exp: {'name': exp} for exp in exports}
            
        except Exception as e:
            logger.error(f"Error analyzing JavaScript file {filepath}: {e}")
            result.error = str(e)
        
        return result

class FallbackAnalyzer(FileAnalyzer):
    """Fallback analyzer for unknown file types."""
    
    def can_analyze(self, filepath: str) -> bool:
        return True  # Can handle any file
    
    def analyze(self, filepath: str) -> FileAnalysisResult:
        """Basic analysis for unknown files."""
        result = FileAnalysisResult(
            filepath=filepath,
            filename=Path(filepath).name,
            file_type=FileType.UNKNOWN,
            overview=f"File: {Path(filepath).name}"
        )
        
        try:
            # Just get basic file info
            stat = Path(filepath).stat()
            result.other_notes = [
                f"File size: {stat.st_size} bytes",
                f"Modified: {stat.st_mtime}"
            ]
        except Exception as e:
            result.error = str(e)
        
        return result

class AnalyzerRegistry:
    """Registry of file analyzers."""
    
    def __init__(self):
        self._analyzers: List[FileAnalyzer] = []
        self._register_default_analyzers()
    
    def _register_default_analyzers(self):
        """Register default analyzers."""
        self.register(PythonAnalyzer())
        self.register(JavaScriptAnalyzer())
        # Add more analyzers as needed
        self.register(FallbackAnalyzer())  # Must be last
    
    def register(self, analyzer: FileAnalyzer):
        """Register a new analyzer."""
        self._analyzers.append(analyzer)
    
    def get_analyzer(self, filepath: str) -> FileAnalyzer:
        """Get appropriate analyzer for file."""
        for analyzer in self._analyzers:
            if analyzer.can_analyze(filepath):
                return analyzer
        
        # Should never reach here if FallbackAnalyzer is registered
        return FallbackAnalyzer()
    
    def analyze_file(self, filepath: str) -> FileAnalysisResult:
        """Analyze a file using appropriate analyzer."""
        analyzer = self.get_analyzer(filepath)
        return analyzer.analyze(filepath)
```

### app/documentation_service.py
```python
from typing import List, Optional, Dict, Any, Iterator
from pathlib import Path
import logging
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

from storage.backend import StorageBackend
from storage.models import FileDocumentation
from dataset.dataset_service import DatasetService
from .documentation_models import (
    DocumentationRequest, DocumentationResult, DocumentationProgress,
    DocumentationStatus, FileAnalysisResult
)
from .file_discovery import FileDiscovery
from .file_analyzer import AnalyzerRegistry
from .progress_tracker import ProgressTracker

logger = logging.getLogger(__name__)

class DocumentationService:
    """
    Orchestrates file documentation workflows across domains.
    
    This service coordinates between the dataset service, storage backend,
    and file analysis to provide high-level documentation operations.
    """
    
    def __init__(self,
                 dataset_service: DatasetService,
                 storage_backend: StorageBackend,
                 analyzer_registry: Optional[AnalyzerRegistry] = None,
                 max_workers: int = 4):
        """
        Initialize documentation service.
        
        Args:
            dataset_service: Service for dataset management
            storage_backend: Storage backend for persistence
            analyzer_registry: Registry of file analyzers
            max_workers: Maximum parallel workers for analysis
        """
        self.datasets = dataset_service
        self.storage = storage_backend
        self.analyzers = analyzer_registry or AnalyzerRegistry()
        self.max_workers = max_workers
        self._active_operations: Dict[str, ProgressTracker] = {}
        self._lock = threading.Lock()
    
    def document_directory(self, request: DocumentationRequest) -> DocumentationResult:
        """
        Document all files in a directory.
        
        Args:
            request: Documentation request parameters
            
        Returns:
            Documentation result with statistics
        """
        start_time = datetime.now()
        progress_tracker = self._create_progress_tracker(request.dataset_name)
        
        try:
            # Create or verify dataset
            dataset = self.datasets.create_dataset(
                dataset_name=request.dataset_name,
                source_dir=request.source_directory
            )
            
            # Discover files
            discovery = FileDiscovery(
                include_patterns=request.include_patterns,
                exclude_patterns=request.exclude_patterns,
                max_file_size=request.max_file_size
            )
            
            files = discovery.discover_files_parallel(request.source_directory)
            logger.info(f"Discovered {len(files)} files to document")
            
            # Initialize progress
            progress_tracker.initialize(total_files=len(files))
            
            # Process files in batches
            documented_count = 0
            failed_count = 0
            skipped_count = 0
            
            for batch in self._batch_files(files, request.batch_size):
                if progress_tracker.is_cancelled():
                    break
                
                batch_results = self._process_batch(
                    batch, 
                    request,
                    progress_tracker
                )
                
                documented_count += batch_results['documented']
                failed_count += batch_results['failed']
                skipped_count += batch_results['skipped']
            
            # Determine final status
            if progress_tracker.is_cancelled():
                status = DocumentationStatus.CANCELLED
            elif failed_count == 0:
                status = DocumentationStatus.COMPLETED
            else:
                status = DocumentationStatus.COMPLETED  # Partial success
            
            elapsed_time = (datetime.now() - start_time).total_seconds()
            
            return DocumentationResult(
                dataset_name=request.dataset_name,
                source_directory=request.source_directory,
                total_files=len(files),
                documented_files=documented_count,
                failed_files=failed_count,
                skipped_files=skipped_count,
                elapsed_time=elapsed_time,
                status=status,
                errors=progress_tracker.get_errors()
            )
            
        finally:
            self._remove_progress_tracker(request.dataset_name)
    
    def update_documentation(self, 
                           dataset_name: str,
                           filepaths: List[str],
                           force: bool = False) -> DocumentationResult:
        """
        Update documentation for specific files.
        
        Args:
            dataset_name: Dataset to update
            filepaths: Files to update
            force: Force update even if unchanged
            
        Returns:
            Documentation result
        """
        start_time = datetime.now()
        
        # Filter files that need updating
        files_to_update = []
        
        for filepath in filepaths:
            if force or self._needs_update(dataset_name, filepath):
                files_to_update.append(filepath)
        
        if not files_to_update:
            return DocumentationResult(
                dataset_name=dataset_name,
                source_directory="",
                total_files=len(filepaths),
                documented_files=0,
                failed_files=0,
                skipped_files=len(filepaths),
                elapsed_time=0,
                status=DocumentationStatus.COMPLETED
            )
        
        # Create request for update
        request = DocumentationRequest(
            dataset_name=dataset_name,
            source_directory="",
            update_existing=True
        )
        
        # Process updates
        progress_tracker = self._create_progress_tracker(f"{dataset_name}_update")
        progress_tracker.initialize(total_files=len(files_to_update))
        
        try:
            batch_results = self._process_batch(
                files_to_update,
                request,
                progress_tracker
            )
            
            elapsed_time = (datetime.now() - start_time).total_seconds()
            
            return DocumentationResult(
                dataset_name=dataset_name,
                source_directory="",
                total_files=len(filepaths),
                documented_files=batch_results['documented'],
                failed_files=batch_results['failed'],
                skipped_files=len(filepaths) - len(files_to_update) + batch_results['skipped'],
                elapsed_time=elapsed_time,
                status=DocumentationStatus.COMPLETED,
                errors=progress_tracker.get_errors()
            )
        finally:
            self._remove_progress_tracker(f"{dataset_name}_update")
    
    def get_progress(self, dataset_name: str) -> Optional[DocumentationProgress]:
        """Get progress for active documentation operation."""
        with self._lock:
            tracker = self._active_operations.get(dataset_name)
            return tracker.get_progress() if tracker else None
    
    def cancel_documentation(self, dataset_name: str) -> bool:
        """Cancel active documentation operation."""
        with self._lock:
            tracker = self._active_operations.get(dataset_name)
            if tracker:
                tracker.cancel()
                return True
            return False
    
    def _create_progress_tracker(self, operation_id: str) -> ProgressTracker:
        """Create and register progress tracker."""
        with self._lock:
            tracker = ProgressTracker(operation_id)
            self._active_operations[operation_id] = tracker
            return tracker
    
    def _remove_progress_tracker(self, operation_id: str):
        """Remove progress tracker."""
        with self._lock:
            self._active_operations.pop(operation_id, None)
    
    def _process_batch(self,
                      files: List[str],
                      request: DocumentationRequest,
                      progress_tracker: ProgressTracker) -> Dict[str, int]:
        """Process a batch of files."""
        results = {
            'documented': 0,
            'failed': 0,
            'skipped': 0
        }
        
        # Analyze files in parallel
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_file = {
                executor.submit(self._analyze_and_store, filepath, request): filepath
                for filepath in files
            }
            
            for future in as_completed(future_to_file):
                if progress_tracker.is_cancelled():
                    # Cancel remaining futures
                    for f in future_to_file:
                        f.cancel()
                    break
                
                filepath = future_to_file[future]
                
                try:
                    result = future.result()
                    if result == 'documented':
                        results['documented'] += 1
                    elif result == 'skipped':
                        results['skipped'] += 1
                    else:
                        results['failed'] += 1
                    
                    progress_tracker.update(filepath, result == 'documented')
                    
                except Exception as e:
                    logger.error(f"Error processing {filepath}: {e}")
                    results['failed'] += 1
                    progress_tracker.update(filepath, False, str(e))
        
        return results
    
    def _analyze_and_store(self, 
                          filepath: str,
                          request: DocumentationRequest) -> str:
        """Analyze file and store documentation."""
        try:
            # Check if update needed
            if not request.update_existing:
                existing = self.storage.get_file_documentation(
                    filepath, 
                    request.dataset_name
                )
                if existing:
                    return 'skipped'
            
            # Analyze file
            analysis_result = self.analyzers.analyze_file(filepath)
            
            if analysis_result.error:
                logger.error(f"Analysis error for {filepath}: {analysis_result.error}")
                return 'failed'
            
            # Convert to storage model
            doc = self._convert_to_documentation(analysis_result)
            
            # Store in backend
            success = self.storage.insert_documentation(doc, request.dataset_name)
            
            return 'documented' if success else 'failed'
            
        except Exception as e:
            logger.error(f"Error processing {filepath}: {e}")
            return 'failed'
    
    def _convert_to_documentation(self, analysis: FileAnalysisResult) -> FileDocumentation:
        """Convert analysis result to storage model."""
        return FileDocumentation(
            filepath=analysis.filepath,
            filename=analysis.filename,
            overview=analysis.overview or f"Documentation for {analysis.filename}",
            ddd_context=analysis.ddd_context,
            functions=analysis.functions,
            exports=analysis.exports,
            imports=analysis.imports,
            types_interfaces_classes=analysis.types_interfaces_classes,
            constants=analysis.constants,
            dependencies=analysis.dependencies,
            other_notes=analysis.other_notes,
            full_content=None,  # Not storing content by default
            documented_at=datetime.now()
        )
    
    def _needs_update(self, dataset_name: str, filepath: str) -> bool:
        """Check if file needs documentation update."""
        existing = self.storage.get_file_documentation(filepath, dataset_name)
        if not existing:
            return True
        
        # Check file modification time
        try:
            file_mtime = Path(filepath).stat().st_mtime
            doc_time = existing.documented_at.timestamp() if existing.documented_at else 0
            return file_mtime > doc_time
        except:
            return True
    
    def _batch_files(self, files: List[str], batch_size: int) -> Iterator[List[str]]:
        """Yield batches of files."""
        for i in range(0, len(files), batch_size):
            yield files[i:i + batch_size]
```

### app/progress_tracker.py
```python
from typing import List, Dict, Optional
from datetime import datetime
import threading
from dataclasses import dataclass, field

from .documentation_models import DocumentationProgress

@dataclass
class ProgressTracker:
    """Thread-safe progress tracking for documentation operations."""
    
    operation_id: str
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _progress: Optional[DocumentationProgress] = None
    _cancelled: bool = False
    
    def initialize(self, total_files: int):
        """Initialize progress tracking."""
        with self._lock:
            self._progress = DocumentationProgress(
                total_files=total_files,
                processed_files=0,
                successful_files=0,
                failed_files=0,
                skipped_files=0,
                start_time=datetime.now()
            )
    
    def update(self, filepath: str, success: bool, error: Optional[str] = None):
        """Update progress for a file."""
        with self._lock:
            if not self._progress:
                return
            
            self._progress.processed_files += 1
            self._progress.current_file = filepath
            
            if success:
                self._progress.successful_files += 1
            else:
                self._progress.failed_files += 1
                if error:
                    self._progress.errors.append({
                        'file': filepath,
                        'error': error,
                        'timestamp': datetime.now().isoformat()
                    })
    
    def get_progress(self) -> Optional[DocumentationProgress]:
        """Get current progress snapshot."""
        with self._lock:
            return self._progress
    
    def cancel(self):
        """Cancel the operation."""
        with self._lock:
            self._cancelled = True
    
    def is_cancelled(self) -> bool:
        """Check if operation is cancelled."""
        with self._lock:
            return self._cancelled
    
    def get_errors(self) -> List[Dict[str, str]]:
        """Get all errors."""
        with self._lock:
            return self._progress.errors.copy() if self._progress else []
```

## Required Changes to PR 2 (StorageBackend)

Based on zen's review, PR 2 needs the following methods added to avoid N+1 query problems:

### storage/backend.py additions:
```python
@abstractmethod
def insert_documentation_batch(self, docs: List[FileDocumentation], dataset: str) -> int:
    """Insert multiple file documentations efficiently.
    Returns number of documents successfully inserted."""
    pass

@abstractmethod
def get_file_documentation_batch(self, filepaths: List[str], dataset: str) -> Dict[str, FileDocumentation]:
    """Retrieve documentation for multiple files at once.
    Returns dict mapping filepath to documentation (missing files not in dict)."""
    pass
```

These batch methods are critical for performance with large codebases.

## Testing Plan

### Unit Tests

#### test_file_discovery.py
```python
def test_discover_files_basic():
    """Test basic file discovery."""
    discovery = FileDiscovery()
    files = discovery.discover_files("test_data/sample_project")
    assert len(files) > 0
    assert all(os.path.isfile(f) for f in files)

def test_exclude_patterns():
    """Test exclusion patterns work correctly."""
    discovery = FileDiscovery(exclude_patterns=['*.test.py'])
    files = discovery.discover_files("test_data")
    assert not any(f.endswith('.test.py') for f in files)

def test_include_patterns():
    """Test inclusion patterns work correctly."""
    discovery = FileDiscovery(include_patterns=['*.py'])
    files = discovery.discover_files("test_data")
    assert all(f.endswith('.py') for f in files)

def test_parallel_discovery():
    """Test parallel discovery produces same results."""
    discovery = FileDiscovery()
    serial_files = set(discovery.discover_files("test_data"))
    parallel_files = set(discovery.discover_files_parallel("test_data"))
    assert serial_files == parallel_files
```

#### test_file_analyzer.py
```python
def test_python_analyzer():
    """Test Python file analysis."""
    analyzer = PythonAnalyzer()
    result = analyzer.analyze("test_data/sample.py")
    
    assert result.file_type == FileType.PYTHON
    assert len(result.functions) > 0
    assert result.overview != ""

def test_analyzer_registry():
    """Test analyzer registry."""
    registry = AnalyzerRegistry()
    
    # Python file gets Python analyzer
    analyzer = registry.get_analyzer("test.py")
    assert isinstance(analyzer, PythonAnalyzer)
    
    # Unknown file gets fallback
    analyzer = registry.get_analyzer("test.xyz")
    assert isinstance(analyzer, FallbackAnalyzer)

def test_analyzer_error_handling():
    """Test analyzer handles errors gracefully."""
    analyzer = PythonAnalyzer()
    result = analyzer.analyze("nonexistent.py")
    assert result.error is not None
```

#### test_documentation_service.py
```python
def test_document_directory():
    """Test documenting entire directory."""
    mock_datasets = Mock(DatasetService)
    mock_storage = Mock(StorageBackend)
    
    service = DocumentationService(mock_datasets, mock_storage)
    
    request = DocumentationRequest(
        dataset_name="test_dataset",
        source_directory="test_data",
        batch_size=10
    )
    
    result = service.document_directory(request)
    
    assert result.status == DocumentationStatus.COMPLETED
    assert result.documented_files > 0
    assert mock_storage.insert_documentation.called

def test_batch_processing():
    """Test files are processed in batches."""
    service = DocumentationService(mock_datasets, mock_storage)
    
    files = [f"file{i}.py" for i in range(100)]
    batches = list(service._batch_files(files, 25))
    
    assert len(batches) == 4
    assert all(len(batch) == 25 for batch in batches)

def test_progress_tracking():
    """Test progress tracking during documentation."""
    service = DocumentationService(mock_datasets, mock_storage)
    
    # Start documentation in thread
    import threading
    request = DocumentationRequest("test", "test_data")
    thread = threading.Thread(target=service.document_directory, args=(request,))
    thread.start()
    
    # Check progress
    time.sleep(0.1)
    progress = service.get_progress("test")
    assert progress is not None
    assert progress.total_files > 0

def test_cancellation():
    """Test operation cancellation."""
    service = DocumentationService(mock_datasets, mock_storage)
    
    # Mock slow analysis
    def slow_analyze(*args):
        time.sleep(1)
        return Mock(error=None)
    
    service.analyzers.analyze_file = slow_analyze
    
    # Start and cancel
    thread = threading.Thread(target=service.document_directory, args=(request,))
    thread.start()
    
    time.sleep(0.1)
    cancelled = service.cancel_documentation("test")
    assert cancelled
    
    thread.join()
    progress = service.get_progress("test")
    assert progress is None  # Cleaned up
```

### Integration Tests
```python
def test_end_to_end_documentation():
    """Test complete documentation workflow."""
    # Setup real components
    storage = SqliteBackend(":memory:")
    datasets = DatasetService(storage, Mock())
    service = DocumentationService(datasets, storage)
    
    # Document a directory
    request = DocumentationRequest(
        dataset_name="integration_test",
        source_directory="test_data/sample_project"
    )
    
    result = service.document_directory(request)
    
    # Verify results
    assert result.status == DocumentationStatus.COMPLETED
    assert result.documented_files > 0
    
    # Verify stored documents
    docs = storage.search_metadata("*", "integration_test", 100)
    assert len(docs) == result.documented_files

def test_incremental_update():
    """Test incremental documentation updates."""
    # Initial documentation
    result1 = service.document_directory(request)
    
    # Update should skip unchanged files
    result2 = service.document_directory(request)
    assert result2.skipped_files == result1.documented_files
    
    # Force update
    request.update_existing = True
    result3 = service.document_directory(request)
    assert result3.documented_files == result1.documented_files
```

## Migration Strategy

### Phase 1: Deploy Service
1. Deploy DocumentationService alongside existing code
2. No changes to existing MCP tools initially
3. Service available for testing

### Phase 2: Update MCP Tools
1. Update `document_directory` tool to use DocumentationService
2. Add progress reporting to tool responses
3. Maintain backward compatibility

### Phase 3: Add New Features
1. Add incremental update support
2. Add file-specific update tools
3. Add progress monitoring tools

## Integration Points

### With MCP Tools
```python
# In mcp_tools.py
async def document_directory(dataset_name: str, directory: str, **kwargs):
    """Updated tool using DocumentationService."""
    request = DocumentationRequest(
        dataset_name=dataset_name,
        source_directory=directory,
        **kwargs
    )
    
    result = app_context.documentation_service.document_directory(request)
    
    return {
        'success': result.status == DocumentationStatus.COMPLETED,
        'documented_files': result.documented_files,
        'failed_files': result.failed_files,
        'elapsed_time': result.elapsed_time,
        'errors': result.errors[:10]  # Limit errors in response
    }
```

### With Storage Backend
- Uses StorageBackend.insert_documentation for single files
- Could benefit from batch insert method
- Respects storage transaction boundaries

### With Dataset Service
- Creates datasets before documentation
- Validates dataset existence
- Handles dataset metadata updates

## Performance Considerations

1. **Parallel Analysis**:
   - Configurable worker pool size
   - CPU-bound analysis benefits from parallelism
   - Memory usage scales with workers

2. **Batch Processing**:
   - Reduces storage operation overhead
   - Configurable batch size
   - Progress updates per batch

3. **File Discovery**:
   - Parallel directory traversal for large trees
   - Pattern matching optimizations
   - Early filtering of excluded paths

4. **Memory Management**:
   - Stream large files during analysis
   - Clear analysis results after storage
   - Limit error message retention

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Large file analysis OOM | Process crash | File size limits, streaming analysis |
| Slow analysis blocks progress | Poor UX | Timeouts, cancellation support |
| Concurrent dataset access | Data corruption | Rely on storage layer locking |
| Analysis errors cascade | Batch failures | Individual file error isolation |
| Progress tracking overhead | Performance | Lightweight progress updates |
| Regex JS parser fails | Incorrect documentation | Replace with AST parser (esprima-python) |
| N+1 query problems | Poor performance | Batch operations in StorageBackend |
| Thread safety issues | Race conditions | Deep copy progress snapshots |

## Success Criteria

1. **Functionality**:
   - Successfully documents Python, JS, TS files
   - Batch processing improves throughput
   - Progress tracking provides real-time updates

2. **Performance**:
   - Documents 1000 files in < 60 seconds
   - Parallel analysis uses available CPUs
   - Memory usage remains bounded

3. **Reliability**:
   - Graceful handling of analysis errors
   - Cancellation works cleanly
   - Progress persists across restarts

4. **Extensibility**:
   - Easy to add new language analyzers
   - Clear analyzer interface
   - Pluggable discovery strategies

## Future Enhancements

1. **Advanced Analysis**:
   - LSP-based analysis for better accuracy
   - Cross-file dependency tracking
   - Symbol resolution

2. **Caching**:
   - Cache analysis results by file hash
   - Avoid re-analyzing unchanged files
   - Distributed cache for teams

3. **Streaming**:
   - Stream documentation updates to clients
   - Real-time progress via websockets
   - Live documentation updates

4. **Scheduling**:
   - Background documentation updates
   - Scheduled re-analysis
   - Priority queues for updates

## Review Checklist

- [ ] FileDiscovery handles patterns correctly
- [ ] Analyzers extract meaningful documentation
- [ ] Batch processing includes batch DB operations
- [ ] JavaScript analyzer uses proper AST parser
- [ ] Progress tracking returns immutable snapshots
- [ ] Batch metadata fetching avoids N+1 queries
- [ ] Python version compatibility (3.8+)
- [ ] COMPLETED_WITH_ERRORS status for partial success
- [ ] Cancellation works reliably
- [ ] Error handling is comprehensive
- [ ] Integration preserves existing functionality
- [ ] Tests cover edge cases