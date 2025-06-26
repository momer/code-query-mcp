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
            "table_prefix": f"data_{sanitized_branch}"  # e.g., data_main, data_feature_new_ui
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