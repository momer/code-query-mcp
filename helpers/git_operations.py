"""Git operations helper class for dataset management."""

import subprocess
import logging
import os
from typing import List, Optional

logger = logging.getLogger(__name__)


class GitHelper:
    """Simple wrapper for git operations used by dataset management."""
    
    def __init__(self):
        pass
        
    def run_command(self, cmd: List[str], cwd: Optional[str] = None) -> str:
        """
        Run a git command and return output.
        
        Args:
            cmd: Command as list of strings
            cwd: Working directory for command
            
        Returns:
            Command output as string
            
        Raises:
            subprocess.CalledProcessError: If command fails
        """
        try:
            result = subprocess.run(
                cmd,
                cwd=cwd,
                capture_output=True,
                text=True,
                check=True
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            logger.error(f"Git command failed: {' '.join(cmd)}\nError: {e.stderr}")
            raise
            
    def is_git_repository(self, path: str) -> bool:
        """
        Check if a path is inside a git repository.
        
        Args:
            path: Directory path to check
            
        Returns:
            True if path is in a git repository
        """
        try:
            self.run_command(["git", "rev-parse", "--git-dir"], cwd=path)
            return True
        except subprocess.CalledProcessError:
            return False