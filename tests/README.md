# Background Processing Tests

This directory contains unit tests for the background processing system.

## Test Structure

```
tests/
├── __init__.py
├── test_worker_detection.py    # Worker process detection
├── test_queue_operations.py    # Queue management
├── test_config_loading.py      # Configuration handling
├── test_git_hooks.py          # Git hook logic
├── test_error_handling.py      # Error scenarios
├── run_tests.py               # Test runner script
└── fixtures/                  # Test data and fixtures
    └── test_configs.py
```

## Running Tests

### Run all tests:
```bash
python tests/run_tests.py
```

### Run specific test module:
```bash
python -m unittest tests.test_worker_detection
```

### Run specific test case:
```bash
python -m unittest tests.test_worker_detection.TestWorkerDetection.test_no_pid_file
```

### Run with verbose output:
```bash
python -m unittest discover -v
```

## Test Coverage

### Worker Detection (`test_worker_detection.py`)
- ✓ No PID file exists
- ✓ Valid PID file with running process
- ✓ Stale PID file cleanup
- ✓ PID reuse by different process
- ✓ Corrupted PID file handling
- ✓ Access denied scenarios
- ✓ Worker start process

### Queue Operations (`test_queue_operations.py`)
- ✓ Adding files to queue
- ✓ Removing completed files
- ✓ Duplicate file handling
- ✓ Queue clearing
- ✓ Atomic operations
- ✓ Queue status reporting
- ✓ Batch processing
- ✓ Missing file cleanup
- ✓ History tracking
- ✓ File locking

### Configuration Loading (`test_config_loading.py`)
- ✓ Default config creation
- ✓ Valid config loading
- ✓ Validation errors
- ✓ Deep merge of configs
- ✓ Atomic saves
- ✓ Processing mode updates
- ✓ Schema validation
- ✓ Environment variable overrides
- ✓ File permissions

### Git Hooks (`test_git_hooks.py`)
- ✓ Missing config handling
- ✓ Empty queue handling
- ✓ Manual mode processing
- ✓ Auto mode without worker
- ✓ Auto mode with worker
- ✓ Atomic queue clearing
- ✓ Corrupted queue recovery
- ✓ Path traversal prevention
- ✓ Cross-platform worker detection

### Error Handling (`test_error_handling.py`)
- ✓ Task retry mechanism
- ✓ Git hooks never block commits
- ✓ Worker graceful shutdown
- ✓ Queue corruption recovery
- ✓ Path validation security
- ✓ Import error fallback
- ✓ Atomic operation failures
- ✓ Resource cleanup on errors

## Writing New Tests

### Test Template
```python
import unittest
from unittest.mock import Mock, patch

class TestNewFeature(unittest.TestCase):
    def setUp(self):
        """Set up test environment."""
        # Create temp directories, mock objects, etc.
        pass
    
    def tearDown(self):
        """Clean up test environment."""
        # Remove temp files, reset state, etc.
        pass
    
    def test_specific_behavior(self):
        """Test description."""
        # Arrange
        # Act
        # Assert
        pass
```

### Best Practices
1. **Isolation**: Each test should be independent
2. **Mocking**: Mock external dependencies (subprocess, file I/O)
3. **Cleanup**: Always clean up temp files in tearDown
4. **Naming**: Use descriptive test names that explain what's being tested
5. **Coverage**: Test both success and failure paths

## Continuous Integration

To run tests in CI:

```bash
# Install dependencies
pip install -r requirements.txt

# Run tests with exit code
python tests/run_tests.py

# Check exit code
if [ $? -eq 0 ]; then
    echo "All tests passed!"
else
    echo "Tests failed!"
    exit 1
fi
```

## Known Limitations

1. **Concurrency**: Full concurrency testing requires actual process spawning
2. **Huey Integration**: Some Huey-specific features are mocked rather than tested
3. **Cross-platform**: Some tests may behave differently on Windows vs Unix

## Debugging Failed Tests

1. Run with verbose flag: `python -m unittest -v`
2. Add print statements in test code
3. Use `pdb` for interactive debugging:
   ```python
   import pdb; pdb.set_trace()
   ```
4. Check temp directory contents if tests fail
5. Ensure all dependencies are installed

## Future Improvements

- [ ] Add integration tests for full workflow
- [ ] Add performance benchmarks
- [ ] Add code coverage reporting
- [ ] Add mutation testing
- [ ] Add property-based tests for queue operations