"""Test configuration fixtures for unit tests."""

# Valid configurations for testing
VALID_CONFIGS = {
    'minimal': {
        'dataset_name': 'test-project',
        'processing': {
            'mode': 'manual'
        }
    },
    
    'auto_mode': {
        'dataset_name': 'test-project',
        'model': 'claude-3-5-sonnet-20240620',
        'processing': {
            'mode': 'auto',
            'fallback_to_sync': True,
            'batch_size': 10,
            'retry_attempts': 3,
            'retry_delay': 30
        }
    },
    
    'custom_model': {
        'dataset_name': 'test-project',
        'model': 'claude-3-opus-20240229',
        'processing': {
            'mode': 'manual'
        }
    }
}

# Invalid configurations for testing validation
INVALID_CONFIGS = {
    'missing_dataset': {
        'processing': {
            'mode': 'manual'
        }
    },
    
    'invalid_mode': {
        'dataset_name': 'test',
        'processing': {
            'mode': 'invalid-mode'
        }
    },
    
    'wrong_types': {
        'dataset_name': 'test',
        'processing': {
            'mode': 'manual',
            'batch_size': 'five',  # Should be int
            'fallback_to_sync': 'yes'  # Should be bool
        }
    }
}

# Test file contents
TEST_FILE_CONTENTS = {
    'simple_python': '''def hello():
    """Say hello."""
    print("Hello, world!")

if __name__ == "__main__":
    hello()
''',
    
    'complex_python': '''import os
import sys
from typing import List, Dict

class DataProcessor:
    """Process data files."""
    
    def __init__(self, config: Dict):
        self.config = config
    
    def process(self, files: List[str]) -> Dict[str, any]:
        """Process a list of files."""
        results = {}
        for file in files:
            results[file] = self._process_file(file)
        return results
    
    def _process_file(self, filepath: str) -> bool:
        """Process a single file."""
        # Implementation here
        return True
''',
    
    'javascript': '''const express = require('express');

class ApiServer {
    constructor(config) {
        this.config = config;
        this.app = express();
    }
    
    start(port = 3000) {
        this.app.listen(port, () => {
            console.log(`Server running on port ${port}`);
        });
    }
}

module.exports = ApiServer;
'''
}