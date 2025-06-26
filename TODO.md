# TODO - Security Fixes and Improvements

## Critical Security Issues

### 1. Argument Injection in sync_dataset (CRITICAL)
**Location**: `storage/sqlite_storage.py:795` (sync_dataset function)
**Issue**: The `source_ref` and `target_ref` parameters are used directly in a git diff command without validation. An attacker could provide a ref name that starts with a dash (e.g., `--output=/tmp/pwned`) which git would interpret as a command-line option.
**Fix**: Add validation to ensure refs don't start with dash and only contain valid git ref characters:
```python
# Add validation for git refs to prevent argument injection
ref_pattern = re.compile(r"^[a-zA-Z0-9_./-]+$")
if not ref_pattern.match(source_ref) or not ref_pattern.match(target_ref):
    return {"success": False, "message": "Invalid source or target ref format."}
if source_ref.startswith('-') or target_ref.startswith('-'):
    return {"success": False, "message": "Invalid source or target ref. Refs cannot start with a dash."}
```

### 2. Command Injection in post-merge hook (CRITICAL)
**Location**: `storage/sqlite_storage.py:1070` (install_post_merge_hook function)
**Issue**: The post-merge hook reads `CURRENT_DATASET` from config.json without validation. If an attacker modifies config.json, they could inject commands.
**Fix**: Add validation inside the generated shell script:
```bash
# Validate the dataset name read from the config file
if ! [[ "$CURRENT_DATASET" =~ ^[a-zA-Z0-9_.-]+$ ]]; then
    echo "⚠️  Code Query: Invalid dataset name found in config: $CURRENT_DATASET"
    exit 0
fi
```

## High Priority Issues

### 3. Dataset name validation allows path traversal (HIGH)
**Location**: `storage/sqlite_storage.py:919` and `1045`
**Issue**: The regex `^[a-zA-Z0-9_.-]+$` allows dataset names like `.` or `..` which could lead to path traversal vulnerabilities.
**Fix**: Explicitly disallow `.` and `..`:
```python
if not re.match(r'^[a-zA-Z0-9_.-]+$', dataset_name) or dataset_name in ('.', '..'):
    return {
        "success": False,
        "message": "Invalid dataset_name. Only alphanumeric characters, underscore, dot, and hyphen are allowed, and it cannot be '.' or '..'."
    }
```

### 4. Security of install_pre_commit_hook depends on external script (HIGH)
**Location**: `storage/sqlite_storage.py:1070`
**Issue**: The function executes `install-pre-commit-hook.sh` script. Security depends on how that script handles arguments.
**Action**: Review and ensure the shell script properly quotes all arguments when using them in commands.

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