# Code Review Request: Fix Git Hooks Installation in Worktrees

## Problem Description

Users are encountering errors when trying to install git hooks in a git worktree:

```
Error installing pre-commit hook: [Errno 20] Not a directory: '/home/momer/projects/dcek/mhub-hds/feat-wire-up-device-connection/.git/hooks/pre-commit'
```

This occurs because in a git worktree, `.git` is a file (not a directory) that points to the actual git directory.

## Root Cause Analysis

1. Current implementation assumes `.git` is always a directory:
   ```python
   git_dir = os.path.join(self.cwd, ".git")
   hook_path = os.path.join(git_dir, "hooks", "pre-commit")
   ```

2. In a worktree, `.git` is a file containing:
   ```
   gitdir: /path/to/main/repo/.git/worktrees/worktree-name
   ```

3. This causes `os.path.join(git_dir, "hooks", "pre-commit")` to fail because it tries to treat a file as a directory.

## Proposed Solution

Add a helper method `_get_actual_git_dir()` that uses `git rev-parse --git-dir` to get the correct git directory path, which handles both regular repos and worktrees.

### New Helper Method

```python
def _get_actual_git_dir(self) -> Optional[str]:
    """Determines the actual .git directory path, handling worktrees."""
    try:
        git_dir_result = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            cwd=self.cwd,
            capture_output=True,
            text=True,
            check=True,
            timeout=10
        )
        # git rev-parse --git-dir returns path relative to CWD or absolute.
        # We need the absolute path to ensure os.path.join works correctly.
        git_dir_path = git_dir_result.stdout.strip()
        if not os.path.isabs(git_dir_path):
            git_dir_path = os.path.join(self.cwd, git_dir_path)
        actual_git_dir = os.path.abspath(git_dir_path)
        return actual_git_dir
    except FileNotFoundError:
        logging.error("git command not found. Please ensure Git is installed and in your PATH.")
        return None
    except subprocess.CalledProcessError as e:
        logging.error(f"git command failed: {e.cmd} returned {e.returncode}. Stderr: {e.stderr.strip()}")
        return None
    except subprocess.TimeoutExpired:
        logging.error("git command timed out.")
        return None
    except OSError as e:
        logging.error(f"OS error running git command: {e}")
        return None
```

### Changes to install_pre_commit_hook

Replace:
```python
# Check if we're in a git repository
git_dir = os.path.join(self.cwd, ".git")
if not os.path.exists(git_dir):
    return {
        "success": False,
        "message": "Not in a git repository. Please run this from the root of your git project."
    }
```

With:
```python
actual_git_dir = self._get_actual_git_dir()
if not actual_git_dir:
    return {
        "success": False,
        "message": "Could not determine git repository directory. Please ensure Git is installed and you are in a git repository."
    }

hooks_dir = os.path.join(actual_git_dir, "hooks")
os.makedirs(hooks_dir, exist_ok=True)  # Ensure hooks directory exists
```

And update hook path:
```python
# Write pre-commit hook
hook_path = os.path.join(hooks_dir, "pre-commit")  # Use hooks_dir instead of git_dir
```

### Changes to install_post_merge_hook

Apply the same pattern - use `_get_actual_git_dir()` and ensure the hooks directory exists.

### Changes to get_project_config

For consistency, update to use `_get_actual_git_dir()` instead of direct path checking.

## Benefits

1. **Worktree Support**: Hooks will be installed in the correct location for both regular repos and worktrees
2. **Worktree-Specific Hooks**: Each worktree gets its own hooks, which is good for our use case where different worktrees may have different dataset configurations
3. **Better Error Handling**: Provides clear error messages when git is not available or not in a repository
4. **Consistent Implementation**: All git directory detection uses the same reliable method

## Potential Concerns

1. **Directory Permissions**: We need `os.makedirs(hooks_dir, exist_ok=True)` because the hooks directory might not exist in a fresh worktree
2. **Backward Compatibility**: This change maintains full compatibility with regular git repositories
3. **Error Messages**: Updated error messages to be more helpful when git operations fail

## Testing Considerations

1. Test in a regular git repository - should work as before
2. Test in a git worktree - should successfully install hooks
3. Test outside a git repository - should fail gracefully with clear error message
4. Test with git not installed - should fail gracefully with clear error message

## Alternative Approaches Considered

1. **Tell users to install from main worktree**: This would work but is a poor user experience
2. **Check if .git is a file and parse it**: More complex and error-prone than using git's built-in command
3. **Install hooks in main repo's .git/hooks**: Would require accessing parent directories and wouldn't support worktree-specific configurations

## Questions for Review

1. Is the error handling comprehensive enough?
2. Should we add any additional logging for debugging?
3. Are there any edge cases we haven't considered?
4. Should we update any documentation about worktree support?

Please review this proposed fix and let me know if you see any issues or have suggestions for improvement.