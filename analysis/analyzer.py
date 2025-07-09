"""Core file analysis logic extracted from tasks.py."""

import subprocess
import os
import logging
from typing import Dict, Any
from storage.sqlite_storage import CodeQueryServer
from .parser import parse_claude_response

logger = logging.getLogger(__name__)


class FileAnalyzer:
    """Encapsulates the logic for analyzing a single file."""

    def __init__(self, project_root: str, storage: CodeQueryServer, model: str = 'sonnet'):
        self.project_root = os.path.realpath(project_root)
        self.storage = storage
        self.model = model

    def validate_filepath(self, filepath: str) -> str:
        """
        Performs security validation and returns the absolute path.
        Raises exceptions on validation failure.
        """
        abs_filepath = os.path.join(self.project_root, filepath)
        real_filepath = os.path.realpath(abs_filepath)
        
        # Security check: Ensure resolved path is within project root
        if os.path.commonpath([real_filepath, self.project_root]) != self.project_root:
            raise PermissionError(f"Security violation: File {filepath} resolves outside project root")
        
        if not os.path.isfile(real_filepath):
            raise FileNotFoundError(f"File not found or not a regular file: {filepath}")
        
        return real_filepath

    def analyze_and_document(self,
                           filepath: str,
                           dataset_name: str,
                           commit_hash: str) -> Dict[str, Any]:
        """
        Analyzes a file with Claude and stores the documentation.
        
        Returns:
            Dict with analysis results and metadata
            
        Raises:
            PermissionError: If file is outside project root
            FileNotFoundError: If file doesn't exist
            Exception: If Claude analysis fails
        """
        # 1. Validation
        real_filepath = self.validate_filepath(filepath)
        
        # 2. Read file content
        try:
            with open(real_filepath, 'r', encoding='utf-8') as f:
                file_content = f.read()
        except Exception as e:
            logger.error(f"Failed to read file {filepath}: {e}")
            raise

        # 3. Analyze with Claude (using stdin for security)
        analysis_result = self._call_claude(filepath, file_content)
        
        # 4. Parse response
        documentation = parse_claude_response(analysis_result)
        
        # 5. Update database
        self.storage.update_file_documentation(
            dataset_name=dataset_name,
            filepath=filepath,
            commit_hash=commit_hash,
            **documentation
        )
        
        return {
            "filepath": filepath,
            "success": True,
            "documentation": documentation
        }

    def _call_claude(self, filepath: str, content: str) -> str:
        """
        Call Claude API with proper security measures.
        Passes content via stdin to handle large files and prevent command injection.
        """
        prompt = (
            f'Analyze and document the code in the provided file ({filepath}). '
            f'Focus on its purpose, main functions, exports, imports, and key implementation details.\n\n'
            f'File content:\n{content}'
        )
        
        try:
            # Check if claude CLI supports stdin mode
            # First try with stdin, fallback to argument if needed
            result = subprocess.run(
                ['claude', '-p', '-', '--model', self.model],  # '-' indicates stdin input
                input=prompt,
                capture_output=True, 
                text=True, 
                cwd=self.project_root, 
                timeout=60, 
                check=False
            )
            
            # If stdin mode failed, try the old way as fallback
            # TODO: This check is brittle as it depends on the CLI's error string.
            # A more robust solution would be to check the `claude --version` or
            # look for a more specific error code if available.
            if result.returncode != 0 and ("invalid" in result.stderr.lower() or "unrecognized" in result.stderr.lower()):
                logger.warning("Claude CLI may not support stdin mode ('-p -'), using fallback")
                # Only for small files to avoid ARG_MAX issues
                if len(prompt) > 100000:  # ~100KB threshold
                    raise Exception(f"File too large for command-line argument mode ({len(prompt)} chars)")
                
                result = subprocess.run(
                    ['claude', '-p', prompt, '--model', self.model],
                    capture_output=True, 
                    text=True, 
                    cwd=self.project_root, 
                    timeout=60, 
                    check=False
                )
            
            if result.returncode != 0:
                error_summary = (result.stderr or "No stderr output").splitlines()[0] if result.stderr else "Unknown error"
                error_msg = f"Claude processing failed with exit code {result.returncode}"
                logger.error(f"{error_msg}. stderr: {result.stderr}")
                raise Exception(f"{error_msg}. First error: {error_summary}")
            
            return result.stdout
            
        except subprocess.TimeoutExpired:
            logger.error(f"Claude analysis timed out for {filepath}")
            raise Exception(f"Claude analysis timed out after 60 seconds")
        except Exception as e:
            logger.error(f"Failed to analyze {filepath} with Claude: {e}")
            raise