"""File discovery service for finding code files to document."""

import subprocess
import os
import fnmatch
import glob
from typing import List, Tuple, Optional, Dict
import logging

logger = logging.getLogger(__name__)


class FileDiscoveryService:
    """
    Service for discovering code files in a project.
    Prefers git-tracked files when available, falls back to filesystem traversal.
    """
    
    # Default patterns to exclude
    DEFAULT_EXCLUDES = [
        'node_modules/*', 'dist/*', 'build/*', '.git/*', '*.pyc', '__pycache__/*',
        'venv/*', '.env', '*.log', '*.tmp', '.DS_Store', 'coverage/*', '.pytest_cache/*'
    ]
    
    # Code file extensions to include
    CODE_EXTENSIONS = [
        '.py', '.js', '.jsx', '.ts', '.tsx', '.java', '.cpp', '.c', '.h', 
        '.go', '.rs', '.rb', '.php', '.swift', '.kt', '.scala', '.r', '.jl'
    ]
    
    def __init__(self, project_root: str):
        """
        Initialize the discovery service.
        
        Args:
            project_root: Absolute path to the project root directory
        """
        self.project_root = os.path.abspath(project_root)
        
    def discover_files(self, 
                      directory: str = ".",
                      exclude_patterns: Optional[List[str]] = None) -> List[str]:
        """
        Discovers all relevant source code files.
        
        Args:
            directory: Directory to search (relative to project root)
            exclude_patterns: Additional patterns to exclude
            
        Returns:
            List of relative file paths from the project root
        """
        # Combine default and user-provided exclusions
        all_excludes = self.DEFAULT_EXCLUDES.copy()
        if exclude_patterns:
            all_excludes.extend(exclude_patterns)
        
        # Convert relative directory to absolute
        if directory == ".":
            search_dir = self.project_root
        else:
            search_dir = os.path.join(self.project_root, directory)
            
        # Try git first, fall back to filesystem
        files = self._discover_with_git(directory, all_excludes)
        if files is None:
            # Git failed, use filesystem traversal
            files = self._discover_with_filesystem(search_dir, all_excludes)
            
        return sorted(files)  # Return sorted for consistent ordering
    
    def _discover_with_git(self, 
                          directory: str,
                          exclude_patterns: List[str]) -> Optional[List[str]]:
        """
        Use git ls-files to discover tracked files.
        
        Returns:
            List of relative paths, or None if git fails
        """
        try:
            # Use git ls-files to get tracked files
            cmd = ["git", "ls-files", "--", directory]
            result = subprocess.run(
                cmd,
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=30,
                check=True
            )
            
            if result.returncode != 0:
                return None
                
            # Parse git output
            git_files = result.stdout.strip().split('\n') if result.stdout.strip() else []
            discovered = []
            
            for file_path in git_files:
                if not file_path:  # Skip empty lines
                    continue
                    
                # Check if it's a code file by extension
                _, ext = os.path.splitext(file_path.lower())
                if ext not in self.CODE_EXTENSIONS:
                    continue
                    
                # Apply exclusion patterns
                if any(fnmatch.fnmatch(file_path, pattern) for pattern in exclude_patterns):
                    continue
                    
                # Verify file exists (in case of pending deletions)
                full_path = os.path.join(self.project_root, file_path)
                if os.path.exists(full_path) and os.path.isfile(full_path):
                    discovered.append(file_path)
            
            logger.info(f"Discovered {len(discovered)} files using git ls-files")
            return discovered
            
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as e:
            logger.debug(f"Git discovery failed: {e}")
            return None
    
    def _discover_with_filesystem(self,
                                 search_dir: str,
                                 exclude_patterns: List[str]) -> List[str]:
        """
        Discover files by walking the filesystem once.
        
        Returns:
            List of relative paths from project root
        """
        discovered = []
        code_extensions_set = set(self.CODE_EXTENSIONS)
        
        # Single walk through the filesystem
        for root, dirs, filenames in os.walk(search_dir):
            # Get relative path of current directory
            rel_dir = os.path.relpath(root, self.project_root)
            
            # Modify dirs in-place to skip excluded directories
            dirs[:] = [d for d in dirs if not self._should_exclude_dir(os.path.join(rel_dir, d), exclude_patterns)]
            
            # Check each file
            for filename in filenames:
                # Check extension
                _, ext = os.path.splitext(filename.lower())
                if ext not in code_extensions_set:
                    continue
                
                # Get relative path
                rel_path = os.path.join(rel_dir, filename)
                if rel_dir == '.':
                    rel_path = filename
                
                # Apply exclusion patterns
                if any(fnmatch.fnmatch(rel_path, pattern) for pattern in exclude_patterns):
                    continue
                
                discovered.append(rel_path)
        
        logger.info(f"Discovered {len(discovered)} files using filesystem traversal")
        return discovered
    
    def _should_exclude_dir(self, dir_path: str, exclude_patterns: List[str]) -> bool:
        """
        Check if a directory should be excluded from traversal.
        This helps os.walk skip entire directory trees.
        """
        # Check exact directory patterns
        for pattern in exclude_patterns:
            # Handle patterns like 'node_modules/*' by checking directory name
            if pattern.endswith('/*'):
                dir_pattern = pattern[:-2]
                if fnmatch.fnmatch(dir_path, dir_pattern):
                    return True
            # Also check if the directory itself matches
            if fnmatch.fnmatch(dir_path, pattern):
                return True
        return False
    
    def get_file_commit_hash(self, filepath: str) -> str:
        """
        Get the latest commit hash for a file.
        
        Args:
            filepath: Relative path to the file
            
        Returns:
            Commit hash or "uncommitted" if not in git
        """
        try:
            result = subprocess.run(
                ["git", "log", "-1", "--format=%H", "--", filepath],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=5,
                check=False  # Don't raise on non-zero exit
            )
            
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
                
        except (subprocess.SubprocessError, OSError):
            pass
            
        return "uncommitted"
    
    def get_files_with_commit_hashes(self, 
                                   directory: str = ".",
                                   exclude_patterns: Optional[List[str]] = None) -> List[Dict[str, str]]:
        """
        Efficiently discover files and their latest commit hashes.
        
        Args:
            directory: Directory to search (relative to project root)
            exclude_patterns: Additional patterns to exclude
            
        Returns:
            List of dicts with 'filepath' and 'commit_hash' keys
        """
        # First discover files
        files = self.discover_files(directory, exclude_patterns)
        
        if not files:
            return []
        
        # Try to get all commit hashes efficiently
        file_info = []
        
        try:
            # Use git ls-tree to get current tree hashes for all files at once
            # This is more efficient than calling git log for each file
            result = subprocess.run(
                ["git", "ls-tree", "-r", "HEAD", "--"] + files,
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=30,
                check=False
            )
            
            if result.returncode == 0 and result.stdout:
                # Parse git ls-tree output
                # Format: <mode> <type> <hash>\t<file>
                hash_map = {}
                for line in result.stdout.strip().split('\n'):
                    if not line:
                        continue
                    parts = line.split('\t')
                    if len(parts) == 2:
                        file_path = parts[1]
                        # Get the hash from the first part
                        tree_info = parts[0].split()
                        if len(tree_info) >= 3:
                            hash_map[file_path] = tree_info[2][:12]  # Use short hash
                
                # Build result with hashes
                for filepath in files:
                    file_info.append({
                        'filepath': filepath,
                        'commit_hash': hash_map.get(filepath, "uncommitted")
                    })
            else:
                # Git failed, use fallback
                for filepath in files:
                    file_info.append({
                        'filepath': filepath,
                        'commit_hash': self.get_file_commit_hash(filepath)
                    })
                    
        except (subprocess.SubprocessError, OSError) as e:
            logger.warning(f"Failed to get commit hashes efficiently: {e}")
            # Fallback to individual queries
            for filepath in files:
                file_info.append({
                    'filepath': filepath,
                    'commit_hash': self.get_file_commit_hash(filepath)
                })
        
        return file_info