"""Handles Git worktree detection and management."""

import os
import logging
from typing import Optional, List, Dict
from pathlib import Path

from helpers.git_operations import GitHelper

logger = logging.getLogger(__name__)


class WorktreeHandler:
    """Handles Git worktree detection and management."""
    
    def __init__(self, git_helper: Optional[GitHelper] = None):
        self.git = git_helper or GitHelper()
    
    def is_worktree(self, directory: str) -> bool:
        """
        Check if directory is a Git worktree.
        
        Args:
            directory: Directory to check
            
        Returns:
            True if directory is a worktree
        """
        try:
            # Check if it's a git repository first
            if not self.git.is_git_repository(directory):
                return False
            
            # Get git directory
            git_dir = self.git.run_command(
                ["git", "rev-parse", "--git-dir"],
                cwd=directory
            ).strip()
            
            # Worktrees have .git files, not directories
            git_path = Path(directory) / ".git"
            if git_path.is_file():
                return True
            
            # Also check if git-dir is outside the working directory
            if not git_dir.startswith(directory):
                return True
            
            return False
            
        except Exception as e:
            logger.debug(f"Error checking worktree status: {e}")
            return False
    
    def get_worktree_branch(self, directory: str) -> Optional[str]:
        """
        Get the branch name for a worktree.
        
        Args:
            directory: Worktree directory
            
        Returns:
            Branch name or None
        """
        try:
            branch = self.git.run_command(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=directory
            ).strip()
            
            return branch if branch != "HEAD" else None
            
        except Exception as e:
            logger.error(f"Failed to get worktree branch: {e}")
            return None
    
    def get_main_repository(self, worktree_dir: str) -> Optional[str]:
        """
        Get the main repository path for a worktree.
        
        Args:
            worktree_dir: Worktree directory
            
        Returns:
            Path to main repository
        """
        try:
            # Get the common git directory
            common_dir = self.git.run_command(
                ["git", "rev-parse", "--git-common-dir"],
                cwd=worktree_dir
            ).strip()
            
            # Main repo is parent of common dir
            return str(Path(common_dir).parent)
            
        except Exception as e:
            logger.error(f"Failed to get main repository: {e}")
            return None
    
    def list_worktrees(self, main_repo: str) -> List[Dict[str, str]]:
        """
        List all worktrees for a repository.
        
        Args:
            main_repo: Main repository path
            
        Returns:
            List of worktree info dicts
        """
        try:
            output = self.git.run_command(
                ["git", "worktree", "list", "--porcelain"],
                cwd=main_repo
            )
            
            worktrees = []
            current = {}
            
            for line in output.strip().split('\n'):
                if not line:
                    if current:
                        worktrees.append(current)
                        current = {}
                elif line.startswith("worktree "):
                    current['path'] = line[9:]
                elif line.startswith("branch "):
                    current['branch'] = line[7:]
                elif line.startswith("HEAD "):
                    current['head'] = line[5:]
            
            if current:
                worktrees.append(current)
            
            return worktrees
            
        except Exception as e:
            logger.error(f"Failed to list worktrees: {e}")
            return []
    
    def worktree_exists(self, worktree_path: str) -> bool:
        """
        Check if a worktree path still exists and is valid.
        
        Args:
            worktree_path: Path to check
            
        Returns:
            True if worktree exists and is valid
        """
        # Check if directory exists
        if not os.path.exists(worktree_path):
            return False
        
        # Check if it's still a valid worktree
        return self.is_worktree(worktree_path)
    
    def get_worktree_dataset_name(self, 
                                 main_dataset: str,
                                 branch: str) -> str:
        """
        Generate dataset name for a worktree.
        
        Args:
            main_dataset: Main dataset name
            branch: Worktree branch name
            
        Returns:
            Generated dataset name
        """
        # Clean branch name for use in dataset name
        clean_branch = branch.replace('/', '_').replace('-', '_')
        return f"{main_dataset}__wt_{clean_branch}"