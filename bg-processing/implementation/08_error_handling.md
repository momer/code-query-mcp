# Step 8: Error Handling Framework

## Overview
Implement a basic error handling framework with custom exceptions and enqueue failure handling with fallback.

## References
- phase2_pr_plan.md:108-189 (adapted for Phase 1)
- Zen's feedback on error handling and fallback

## Implementation Tasks

### 8.1 Create helpers/error_handler.py

```python
import sys
import traceback
import logging
from typing import Optional, Dict, Any, Callable
from enum import Enum
from datetime import datetime

class ErrorSeverity(Enum):
    """Error severity levels."""
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"

class CodeQueryError(Exception):
    """Base exception for code-query errors."""
    
    def __init__(
        self, 
        message: str, 
        severity: ErrorSeverity = ErrorSeverity.ERROR,
        context: Optional[Dict[str, Any]] = None,
        recoverable: bool = True
    ):
        super().__init__(message)
        self.severity = severity
        self.context = context or {}
        self.recoverable = recoverable
        self.timestamp = datetime.now()

# Specific error types

class WorkerError(CodeQueryError):
    """Base class for worker-related errors."""
    pass

class WorkerNotRunningError(WorkerError):
    """Raised when worker is expected but not running."""
    
    def __init__(self):
        super().__init__(
            "Background worker is not running",
            severity=ErrorSeverity.WARNING,
            context={
                'suggestion': 'Run "python server.py worker start" to enable background processing',
                'fallback': 'Processing will continue synchronously'
            },
            recoverable=True
        )

class WorkerStartupError(WorkerError):
    """Raised when worker fails to start."""
    
    def __init__(self, reason: str):
        super().__init__(
            f"Failed to start worker: {reason}",
            severity=ErrorSeverity.ERROR,
            context={
                'suggestion': 'Check logs for details. Run "python server.py worker diagnose"'
            },
            recoverable=False
        )

class ConfigurationError(CodeQueryError):
    """Raised when configuration is invalid."""
    
    def __init__(self, message: str, field: Optional[str] = None):
        context = {}
        if field:
            context['field'] = field
            context['suggestion'] = f'Check the "{field}" field in your configuration'
        
        super().__init__(
            message,
            severity=ErrorSeverity.ERROR,
            context=context,
            recoverable=False
        )

class QueueError(CodeQueryError):
    """Base class for queue-related errors."""
    pass

class QueueLockError(QueueError):
    """Raised when queue lock cannot be acquired."""
    
    def __init__(self, timeout: float):
        super().__init__(
            f"Could not acquire queue lock within {timeout}s",
            severity=ErrorSeverity.ERROR,
            context={
                'suggestion': 'Another process may be accessing the queue. Try again.',
                'timeout': timeout
            },
            recoverable=True
        )

class EnqueueError(QueueError):
    """Raised when tasks cannot be enqueued."""
    
    def __init__(self, reason: str, can_fallback: bool = True):
        context = {
            'reason': reason,
            'can_fallback': can_fallback
        }
        
        if can_fallback:
            context['fallback'] = 'Tasks will be processed synchronously'
        
        super().__init__(
            f"Failed to enqueue tasks: {reason}",
            severity=ErrorSeverity.WARNING if can_fallback else ErrorSeverity.ERROR,
            context=context,
            recoverable=can_fallback
        )

class ProcessingError(CodeQueryError):
    """Raised during file processing."""
    
    def __init__(self, filepath: str, reason: str):
        super().__init__(
            f"Failed to process {filepath}: {reason}",
            severity=ErrorSeverity.ERROR,
            context={
                'filepath': filepath,
                'reason': reason
            },
            recoverable=True
        )

# Error handler implementation

class ErrorHandler:
    """Centralized error handling with logging and user feedback."""
    
    def __init__(self, log_file: Optional[str] = None):
        self.log_file = log_file
        self.logger = self._setup_logger()
    
    def _setup_logger(self) -> logging.Logger:
        """Set up error logger."""
        logger = logging.getLogger('code-query.errors')
        logger.setLevel(logging.DEBUG)
        
        # Console handler for warnings and above
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.WARNING)
        console_formatter = logging.Formatter('%(levelname)s: %(message)s')
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)
        
        # File handler for all levels
        if self.log_file:
            file_handler = logging.FileHandler(self.log_file)
            file_handler.setLevel(logging.DEBUG)
            file_formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            file_handler.setFormatter(file_formatter)
            logger.addHandler(file_handler)
        
        return logger
    
    def handle_error(
        self, 
        error: Exception, 
        verbose: bool = False,
        exit_on_critical: bool = True
    ) -> bool:
        """
        Handle an error with appropriate logging and user feedback.
        
        Args:
            error: The exception to handle
            verbose: Show detailed error information
            exit_on_critical: Exit program on critical errors
            
        Returns:
            bool: True if error was recoverable
        """
        if isinstance(error, CodeQueryError):
            return self._handle_codequery_error(error, verbose, exit_on_critical)
        else:
            return self._handle_generic_error(error, verbose)
    
    def _handle_codequery_error(
        self, 
        error: CodeQueryError, 
        verbose: bool,
        exit_on_critical: bool
    ) -> bool:
        """Handle CodeQueryError instances."""
        # Log the error
        log_method = getattr(self.logger, error.severity.value)
        log_method(f"{error}: {error.context}")
        
        # User output
        prefix = f"[{error.severity.value.upper()}]"
        print(f"{prefix} {error}")
        
        # Show suggestions
        if error.context.get('suggestion'):
            print(f"💡 {error.context['suggestion']}")
        
        # Show fallback info
        if error.context.get('fallback'):
            print(f"ℹ️  {error.context['fallback']}")
        
        # Verbose output
        if verbose and error.context:
            print("\nError Context:")
            for key, value in error.context.items():
                if key not in ['suggestion', 'fallback']:
                    print(f"  {key}: {value}")
        
        # Handle critical errors
        if error.severity == ErrorSeverity.CRITICAL and exit_on_critical:
            print("\n❌ Critical error - exiting")
            sys.exit(1)
        
        return error.recoverable
    
    def _handle_generic_error(self, error: Exception, verbose: bool) -> bool:
        """Handle generic exceptions."""
        self.logger.error(f"Unexpected error: {error}", exc_info=True)
        
        # User output (avoid exposing sensitive information)
        print("[ERROR] An unexpected error occurred.")
        
        if verbose:
            print(f"\nDetails: {error}")
            print("\nTraceback:")
            traceback.print_exc()
        else:
            print("💡 Run with --verbose flag for more details.")
        
        return False

# Utility functions

def with_error_handling(
    func: Callable,
    fallback: Optional[Callable] = None,
    error_handler: Optional[ErrorHandler] = None
):
    """
    Decorator to add error handling to functions.
    
    Args:
        func: Function to wrap
        fallback: Optional fallback function
        error_handler: ErrorHandler instance
        
    Returns:
        Wrapped function
    """
    def wrapper(*args, **kwargs):
        handler = error_handler or ErrorHandler()
        
        try:
            return func(*args, **kwargs)
        except Exception as e:
            recoverable = handler.handle_error(e)
            
            if recoverable and fallback:
                print("Attempting fallback...")
                try:
                    return fallback(*args, **kwargs)
                except Exception as fallback_error:
                    handler.handle_error(fallback_error)
                    raise
            else:
                raise
    
    return wrapper

def handle_enqueue_failure(
    error: Exception,
    files: list,
    config: dict,
    fallback_processor: Callable
) -> bool:
    """
    Handle enqueue failures with appropriate fallback.
    
    Args:
        error: The enqueue error
        files: Files that failed to enqueue
        config: Configuration dictionary
        fallback_processor: Function to process files synchronously
        
    Returns:
        bool: True if handled successfully
    """
    handler = ErrorHandler()
    
    # Wrap in EnqueueError if needed
    if not isinstance(error, EnqueueError):
        error = EnqueueError(str(error))
    
    # Check if fallback is enabled
    fallback_enabled = config.get('processing', {}).get('fallback_to_sync', True)
    
    if fallback_enabled:
        print("⚠️  Failed to enqueue to background worker")
        print("  Falling back to synchronous processing...")
        
        try:
            result = fallback_processor(files, config)
            print("✓ Synchronous processing completed")
            return True
        except Exception as fallback_error:
            handler.handle_error(
                ProcessingError("batch", str(fallback_error))
            )
            return False
    else:
        handler.handle_error(error)
        return False

# Context manager for error handling

class ErrorContext:
    """Context manager for scoped error handling."""
    
    def __init__(
        self, 
        operation: str,
        handler: Optional[ErrorHandler] = None,
        suppress: bool = False
    ):
        self.operation = operation
        self.handler = handler or ErrorHandler()
        self.suppress = suppress
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_val is not None:
            # Log the error with operation context
            self.handler.logger.error(
                f"Error during {self.operation}: {exc_val}",
                exc_info=(exc_type, exc_val, exc_tb)
            )
            
            # Handle the error
            recoverable = self.handler.handle_error(exc_val)
            
            # Suppress if requested and recoverable
            return self.suppress and recoverable
```

### 8.2 Add error recovery utilities

```python
class ErrorRecovery:
    """Utilities for recovering from common errors."""
    
    @staticmethod
    def cleanup_stale_locks(project_root: str) -> int:
        """
        Clean up stale lock files.
        
        Args:
            project_root: Project root directory
            
        Returns:
            int: Number of locks cleaned
        """
        import glob
        cleaned = 0
        
        lock_patterns = [
            '.code-query/*.lock',
            '.code-query/*.tmp'
        ]
        
        for pattern in lock_patterns:
            for lock_file in glob.glob(os.path.join(project_root, pattern)):
                try:
                    # Check if lock is stale (older than 1 hour)
                    mtime = os.path.getmtime(lock_file)
                    age = time.time() - mtime
                    
                    if age > 3600:  # 1 hour
                        os.unlink(lock_file)
                        cleaned += 1
                except OSError:
                    pass
        
        return cleaned
    
    @staticmethod
    def repair_corrupted_queue(queue_file: str) -> bool:
        """
        Attempt to repair a corrupted queue file.
        
        Args:
            queue_file: Path to queue file
            
        Returns:
            bool: True if repaired
        """
        backup_file = queue_file + '.backup'
        
        try:
            # Try to load and validate
            with open(queue_file, 'r') as f:
                data = json.load(f)
            
            # Validate structure
            if not isinstance(data, dict) or 'files' not in data:
                raise ValueError("Invalid queue structure")
            
            return True  # File is OK
            
        except Exception:
            # File is corrupted, try to recover
            if os.path.exists(backup_file):
                try:
                    # Restore from backup
                    shutil.copy2(backup_file, queue_file)
                    return True
                except Exception:
                    pass
            
            # Create new empty queue
            try:
                with open(queue_file, 'w') as f:
                    json.dump({'files': []}, f)
                return True
            except Exception:
                return False
```

## Testing Checklist
- [ ] Custom errors have appropriate severity levels
- [ ] Error messages are clear and actionable
- [ ] Suggestions help users resolve issues
- [ ] Fallback to sync works on enqueue failure
- [ ] Verbose mode shows detailed information
- [ ] Critical errors exit appropriately
- [ ] Error logging works correctly
- [ ] Recovery utilities fix common issues

## Usage Examples

```python
# In git hook handler
try:
    enqueue_to_huey(files, config)
except Exception as e:
    if not handle_enqueue_failure(e, files, config, process_synchronously):
        sys.exit(1)

# In worker manager
with ErrorContext("worker startup"):
    start_worker()

# Custom error handling
handler = ErrorHandler(log_file='.code-query/errors.log')
try:
    risky_operation()
except Exception as e:
    if not handler.handle_error(e, verbose=args.verbose):
        cleanup_and_exit()
```