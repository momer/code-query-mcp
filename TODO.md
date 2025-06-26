# TODO - Security Fixes and Improvements

## ✅ Completed Security Fixes

### 1. ~~Argument Injection in sync_dataset~~ (COMPLETED)
**Status**: Fixed in commit bb9bda5
**Fix Applied**: Added validation at the start of sync_dataset() to check refs don't start with dash and only contain safe characters.

### 2. ~~Command Injection in post-merge hook~~ (COMPLETED)
**Status**: Fixed in commit bb9bda5
**Fix Applied**: Post-merge hook now validates dataset names from config.json using regex before use.

## ✅ Completed High Priority Issues

### 3. ~~Dataset name validation allows path traversal~~ (COMPLETED)
**Status**: Fixed in commit bb9bda5
**Fix Applied**: Created centralized `_is_valid_dataset_name()` function that explicitly disallows `.` and `..` and path separators.

### 4. ~~Security of install_pre_commit_hook depends on external script~~ (COMPLETED)
**Status**: Fixed in commit bb9bda5
**Fix Applied**: Removed dependency on external scripts by embedding hook logic directly in Python with proper validation.

## Medium Priority Issues

### 5. Inconsistent branch name sanitization (MEDIUM)
**Location**: `storage/sqlite_storage.py:1333` and `helpers/git_helper.py:38`
**Issue**: Different functions use different logic for sanitizing branch names, which could cause orphaned datasets to not be cleaned up.
**Fix**: Use consistent sanitization logic across all functions:
```python
# In cleanup_datasets, use same logic as get_git_info:
sanitized = re.sub(r'[^a-zA-Z0-9_]', '_', branch)
```

## Other Improvements

### 6. Integration Tests (MEDIUM)
**Location**: `tests/integration/`
**Task**: Write comprehensive integration tests for worktree lifecycle:
- Worktree detection in various git configurations
- Auto-forking with edge case branch names
- Sync operation with file additions/deletions
- Cleanup with active vs deleted branches

## Implementation Notes

- All subprocess inputs should be validated before use
- Git refs should never start with dash and should match expected patterns
- Dataset names should be restricted to safe characters
- Shell scripts should properly quote all variables
- Consistent logic should be used for branch name sanitization across the codebase