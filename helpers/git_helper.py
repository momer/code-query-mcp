"""Git helper functions for Code Query MCP Server."""

import os
import subprocess
import re
import logging


def get_git_info(cwd: str = None) -> dict | None:
    """
    Gathers key Git repository information, handling worktrees correctly.

    Returns a dictionary with repo details, or None if not in a git repo.
    """
    if cwd is None:
        cwd = os.getcwd()

    try:
        # Get the common git directory (points to main repo's .git)
        git_common_dir = subprocess.check_output(
            ["git", "rev-parse", "--git-common-dir"], cwd=cwd, text=True, stderr=subprocess.PIPE
        ).strip()
        
        # Convert to absolute path if relative
        if not os.path.isabs(git_common_dir):
            git_common_dir = os.path.abspath(os.path.join(cwd, git_common_dir))
        
        # The main repository root is the parent of the common git directory
        toplevel = os.path.dirname(git_common_dir)

        # Gets the current branch or tag name.
        branch_name = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=cwd, text=True, stderr=subprocess.PIPE
        ).strip()

        # Sanitize the branch name to be a valid table name prefix.
        # Replaces slashes (e.g., 'feature/new-ui') with underscores.
        sanitized_branch = re.sub(r'[^a-zA-Z0-9_]', '_', branch_name)

        return {
            "toplevel_path": toplevel,
            "branch_name": branch_name,
            "sanitized_branch_name": sanitized_branch
        }
    except (subprocess.CalledProcessError, FileNotFoundError):
        # This will trigger if not in a git repo or git is not installed.
        logging.warning("Not a git repository or git command not found. Falling back to local directory.")
        return None


def get_actual_git_dir(cwd: str = None) -> str | None:
    """Determines the actual .git directory path, handling worktrees."""
    if cwd is None:
        cwd = os.getcwd()
        
    try:
        git_dir_result = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
            timeout=10
        )
        git_dir_path = git_dir_result.stdout.strip()
        if not os.path.isabs(git_dir_path):
            git_dir_path = os.path.join(cwd, git_dir_path)
        return os.path.abspath(git_dir_path)
    except FileNotFoundError:
        logging.error("git command not found. Please ensure Git is installed and in your PATH.")
        return None
    except subprocess.CalledProcessError as e:
        logging.error(f"git command failed: {e.cmd} returned {e.returncode}. Stderr: {e.stderr.strip()}")
        return None
    except (subprocess.TimeoutExpired, OSError) as e:
        logging.error(f"Error running git command: {e}")
        return None


def is_worktree(cwd: str = None) -> bool:
    """
    Check if the current directory is a git worktree (not the main worktree).
    
    Returns True if in a linked worktree, False if in main worktree or not in git.
    """
    if cwd is None:
        cwd = os.getcwd()
    
    try:
        # Check if we're inside a work tree at all
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode != 0 or result.stdout.strip() != "true":
            return False
        
        # Check if .git is a file (linked worktree) or directory (main worktree)
        git_path = os.path.join(cwd, ".git")
        if os.path.exists(git_path) and os.path.isfile(git_path):
            return True
        
        # Walk up the directory tree to find .git
        current = cwd
        while current != os.path.dirname(current):  # Stop at root
            git_path = os.path.join(current, ".git")
            if os.path.exists(git_path):
                return os.path.isfile(git_path)
            current = os.path.dirname(current)
        
        return False
        
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return False


def get_main_worktree_path(cwd: str = None) -> str | None:
    """
    Get the path to the main worktree from any worktree.
    
    Returns the absolute path to the main worktree, or None if not in a git repo.
    """
    if cwd is None:
        cwd = os.getcwd()
    
    try:
        # Get the common git directory path
        result = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
            timeout=10
        )
        
        git_common_dir = result.stdout.strip()
        
        # The main worktree is the parent of the .git directory.
        # This is more robust than string stripping.
        return os.path.dirname(git_common_dir)
            
    except (subprocess.CalledProcessError, FileNotFoundError, OSError) as e:
        logging.debug(f"Failed to get main worktree path: {e}")
        return None


def get_worktree_info(cwd: str = None) -> dict | None:
    """
    Get comprehensive worktree information.
    
    Returns a dict with:
    - is_worktree: bool - True if in a linked worktree
    - main_path: str - Path to the main worktree
    - current_path: str - Path to current worktree
    - branch: str - Current branch name
    
    Returns None if not in a git repository.
    """
    if cwd is None:
        cwd = os.getcwd()
    
    git_info = get_git_info(cwd)
    if not git_info:
        return None
    
    is_linked = is_worktree(cwd)
    main_path = get_main_worktree_path(cwd)
    
    # Get the actual worktree path (not just cwd)
    try:
        current_path = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd,
            text=True,
            stderr=subprocess.PIPE
        ).strip()
    except subprocess.CalledProcessError:
        current_path = cwd
    
    return {
        "is_worktree": is_linked,
        "main_path": main_path,
        "current_path": current_path,
        "branch": git_info["branch_name"],
        "sanitized_branch": git_info["sanitized_branch_name"]
    }


def get_current_commit(cwd: str = None) -> str | None:
    """
    Get the current git commit hash.
    
    Returns the current HEAD commit hash, or None if not in a git repo.
    """
    if cwd is None:
        cwd = os.getcwd()
    
    try:
        commit_hash = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], 
            cwd=cwd, 
            text=True, 
            stderr=subprocess.PIPE
        ).strip()
        return commit_hash
    except subprocess.CalledProcessError:
        return None


def get_changed_files_since_commit(commit_hash: str, cwd: str = None) -> list[str]:
    """
    Get list of files changed since the given commit.
    
    Returns a list of file paths that have been modified, added, or deleted
    since the specified commit.
    """
    if cwd is None:
        cwd = os.getcwd()
    
    if not commit_hash:
        return []
    
    try:
        # Use git diff to find changed files
        result = subprocess.check_output(
            ["git", "diff", "--name-only", f"{commit_hash}..HEAD"], 
            cwd=cwd, 
            text=True, 
            stderr=subprocess.PIPE
        ).strip()
        
        if not result:
            return []
        
        return [line.strip() for line in result.split('\n') if line.strip()]
    except subprocess.CalledProcessError:
        return []