"""Utility functions for configuration module."""

import subprocess
from typing import Tuple, Dict, Any


def check_jq_installed() -> Tuple[bool, Dict[str, Any]]:
    """
    Check if jq is installed on the system.
    
    Returns:
        Tuple of (is_installed, error_info)
    """
    try:
        # Try to run jq --version
        result = subprocess.run(
            ["jq", "--version"],
            capture_output=True,
            text=True,
            check=True
        )
        return True, {}
    except subprocess.CalledProcessError:
        error_info = {
            "message": "jq is not installed",
            "fix": "Please install jq: brew install jq (macOS) or apt install jq (Ubuntu/Debian)",
            "reason": "Git hooks require jq for JSON processing"
        }
        return False, error_info
    except FileNotFoundError:
        error_info = {
            "message": "jq command not found",
            "fix": "Please install jq: brew install jq (macOS) or apt install jq (Ubuntu/Debian)",
            "reason": "Git hooks require jq for JSON processing"
        }
        return False, error_info