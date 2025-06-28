# Step 6: Configuration Schema Extensions

## Overview
Extend the configuration schema to support queue processing settings with validation and defaults.

## References
- phase1_pr_plan.md:77-93
- automated_queue_processing_plan.md:77-93

## Implementation Tasks

### 6.1 Update config schema in storage/config_manager.py

```python
import os
import json
from typing import Dict, Any, Optional, List
from pathlib import Path

class ConfigManager:
    """Manages code-query configuration with validation."""
    
    # Default configuration schema
    DEFAULT_CONFIG = {
        "dataset_name": None,  # Required
        "model": "claude-3-5-sonnet-20240620",
        "processing": {
            "mode": "manual",  # "manual" | "auto"
            "fallback_to_sync": True,
            "batch_size": 5,
            "delay_seconds": 300,
            "max_retries": 2,
            "worker_check_interval": 5,
            "queue_timeout": 30
        },
        "exclude_patterns": [
            "*.test.js",
            "*.spec.js",
            "*.test.ts",
            "*.spec.ts",
            "__tests__/*",
            "test/*",
            "tests/*",
            "node_modules/*",
            ".git/*",
            "dist/*",
            "build/*",
            "coverage/*"
        ]
    }
    
    # Valid model choices
    VALID_MODELS = [
        "claude-3-5-sonnet-20240620",
        "claude-3-haiku-20240307",
        "claude-3-opus-20240229",
        # Add more as they become available
    ]
    
    def __init__(self, config_path: str):
        self.config_path = config_path
        self._config_cache = None
        self._last_modified = None
    
    def load_config(self, create_if_missing: bool = False) -> Dict[str, Any]:
        """
        Load configuration from file with caching.
        
        Args:
            create_if_missing: Create default config if file doesn't exist
            
        Returns:
            Dict: Configuration dictionary
            
        Raises:
            ValueError: If configuration is invalid
        """
        # Check cache validity
        if self._config_cache is not None:
            try:
                current_mtime = os.path.getmtime(self.config_path)
                if current_mtime == self._last_modified:
                    return self._config_cache.copy()
            except OSError:
                pass
        
        # Load from file
        if not os.path.exists(self.config_path):
            if create_if_missing:
                self.create_default_config()
            else:
                raise FileNotFoundError(f"Configuration file not found: {self.config_path}")
        
        try:
            with open(self.config_path, 'r') as f:
                config = json.load(f)
            
            # Validate and merge with defaults
            config = self._validate_and_merge_config(config)
            
            # Update cache
            self._config_cache = config
            self._last_modified = os.path.getmtime(self.config_path)
            
            return config.copy()
            
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in config file: {e}")
    
    def save_config(self, config: Dict[str, Any]):
        """
        Save configuration to file atomically.
        
        Args:
            config: Configuration dictionary
            
        Raises:
            ValueError: If configuration is invalid
        """
        # Validate before saving
        validated_config = self._validate_and_merge_config(config)
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
        
        # Write atomically
        temp_path = self.config_path + '.tmp'
        with open(temp_path, 'w') as f:
            json.dump(validated_config, f, indent=2)
        
        os.replace(temp_path, self.config_path)
        
        # Clear cache
        self._config_cache = None
        self._last_modified = None
    
    def get_processing_config(self) -> Dict[str, Any]:
        """
        Get processing-specific configuration.
        
        Returns:
            Dict: Processing configuration with defaults
        """
        config = self.load_config()
        return config.get('processing', self.DEFAULT_CONFIG['processing'].copy())
    
    def update_processing_mode(self, mode: str):
        """
        Update the processing mode.
        
        Args:
            mode: "manual" or "auto"
            
        Raises:
            ValueError: If mode is invalid
        """
        if mode not in ['manual', 'auto']:
            raise ValueError(f"Invalid processing mode: {mode}")
        
        config = self.load_config()
        if 'processing' not in config:
            config['processing'] = {}
        config['processing']['mode'] = mode
        
        self.save_config(config)
    
    def _validate_and_merge_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate configuration and merge with defaults.
        
        Args:
            config: Raw configuration dictionary
            
        Returns:
            Dict: Validated and merged configuration
            
        Raises:
            ValueError: If configuration is invalid
        """
        # Start with defaults
        result = self.DEFAULT_CONFIG.copy()
        
        # Deep merge user config
        result = self._deep_merge(result, config)
        
        # Validate required fields
        if not result.get('dataset_name'):
            raise ValueError("Configuration missing required field: dataset_name")
        
        # Validate model
        if result.get('model') and result['model'] not in self.VALID_MODELS:
            # Allow custom models but warn
            print(f"⚠️  Using custom model: {result['model']}")
        
        # Validate processing config
        processing = result.get('processing', {})
        
        if processing.get('mode') not in ['manual', 'auto']:
            raise ValueError(f"Invalid processing mode: {processing.get('mode')}")
        
        if not isinstance(processing.get('batch_size', 0), int) or processing.get('batch_size', 0) < 1:
            raise ValueError("batch_size must be a positive integer")
        
        if not isinstance(processing.get('delay_seconds', 0), (int, float)) or processing.get('delay_seconds', 0) < 0:
            raise ValueError("delay_seconds must be non-negative")
        
        return result
    
    def _deep_merge(self, base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
        """
        Deep merge two dictionaries.
        
        Args:
            base: Base dictionary (defaults)
            override: Override dictionary (user config)
            
        Returns:
            Dict: Merged dictionary
        """
        result = base.copy()
        
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                # Recursive merge for nested dicts
                result[key] = self._deep_merge(result[key], value)
            else:
                # Override value
                result[key] = value
        
        return result
    
    def create_default_config(self):
        """Create a default configuration file."""
        default = self.DEFAULT_CONFIG.copy()
        
        # Try to infer dataset name from directory
        project_name = Path(os.path.dirname(self.config_path)).parent.name
        default['dataset_name'] = project_name
        
        self.save_config(default)
        print(f"✓ Created default configuration at {self.config_path}")
    
    def validate_config_file(self) -> List[str]:
        """
        Validate the configuration file and return any issues.
        
        Returns:
            List[str]: List of validation issues (empty if valid)
        """
        issues = []
        
        try:
            config = self.load_config()
            
            # Check for deprecated fields
            if 'auto_process' in config:
                issues.append("Deprecated field 'auto_process' found. Use 'processing.mode' instead.")
            
            # Check for unknown top-level fields
            known_fields = {'dataset_name', 'model', 'processing', 'exclude_patterns'}
            unknown_fields = set(config.keys()) - known_fields
            if unknown_fields:
                issues.append(f"Unknown configuration fields: {', '.join(unknown_fields)}")
            
            # Check processing config
            if 'processing' in config:
                processing = config['processing']
                known_processing_fields = {
                    'mode', 'fallback_to_sync', 'batch_size', 
                    'delay_seconds', 'max_retries', 'worker_check_interval',
                    'queue_timeout'
                }
                unknown_processing = set(processing.keys()) - known_processing_fields
                if unknown_processing:
                    issues.append(f"Unknown processing fields: {', '.join(unknown_processing)}")
            
        except Exception as e:
            issues.append(f"Error loading configuration: {e}")
        
        return issues
```

### 6.2 Add configuration migration support

```python
class ConfigMigrator:
    """Handle configuration schema migrations."""
    
    @staticmethod
    def migrate_config(config: Dict[str, Any], from_version: Optional[int] = None) -> Dict[str, Any]:
        """
        Migrate configuration to latest schema version.
        
        Args:
            config: Current configuration
            from_version: Source schema version (None for auto-detect)
            
        Returns:
            Dict: Migrated configuration
        """
        # Auto-detect version if not specified
        if from_version is None:
            from_version = ConfigMigrator._detect_version(config)
        
        # Apply migrations in sequence
        if from_version < 1:
            config = ConfigMigrator._migrate_v0_to_v1(config)
        
        if from_version < 2:
            config = ConfigMigrator._migrate_v1_to_v2(config)
        
        return config
    
    @staticmethod
    def _detect_version(config: Dict[str, Any]) -> int:
        """Detect configuration schema version."""
        # V2: Has 'processing' section
        if 'processing' in config:
            return 2
        
        # V1: Has 'auto_process' field
        if 'auto_process' in config:
            return 1
        
        # V0: Original schema
        return 0
    
    @staticmethod
    def _migrate_v0_to_v1(config: Dict[str, Any]) -> Dict[str, Any]:
        """Migrate from v0 to v1 schema."""
        # V1 added auto_process field
        if 'auto_process' not in config:
            config['auto_process'] = False
        return config
    
    @staticmethod
    def _migrate_v1_to_v2(config: Dict[str, Any]) -> Dict[str, Any]:
        """Migrate from v1 to v2 schema."""
        # V2 moved auto_process to processing.mode
        if 'auto_process' in config:
            auto_process = config.pop('auto_process')
            if 'processing' not in config:
                config['processing'] = {}
            config['processing']['mode'] = 'auto' if auto_process else 'manual'
        
        return config
```

### 6.3 Add environment variable support

```python
def load_config_with_env_override(config_manager: ConfigManager) -> Dict[str, Any]:
    """
    Load configuration with environment variable overrides.
    
    Environment variables:
    - CODEQUERY_MODEL: Override model
    - CODEQUERY_PROCESSING_MODE: Override processing mode
    - CODEQUERY_BATCH_SIZE: Override batch size
    
    Args:
        config_manager: ConfigManager instance
        
    Returns:
        Dict: Configuration with env overrides applied
    """
    config = config_manager.load_config()
    
    # Model override
    if model := os.environ.get('CODEQUERY_MODEL'):
        config['model'] = model
    
    # Processing mode override
    if mode := os.environ.get('CODEQUERY_PROCESSING_MODE'):
        if mode in ['manual', 'auto']:
            config['processing']['mode'] = mode
    
    # Batch size override
    if batch_size := os.environ.get('CODEQUERY_BATCH_SIZE'):
        try:
            config['processing']['batch_size'] = int(batch_size)
        except ValueError:
            pass
    
    return config
```

## Testing Checklist
- [ ] Default config is created correctly
- [ ] Config validation catches invalid values
- [ ] Deep merge preserves nested structures
- [ ] Atomic saves prevent corruption
- [ ] Config caching improves performance
- [ ] Migration handles old schemas
- [ ] Environment variables override correctly
- [ ] Unknown fields are detected and reported

## Configuration Examples

**Minimal configuration**:
```json
{
  "dataset_name": "my-project"
}
```

**Full configuration**:
```json
{
  "dataset_name": "my-project",
  "model": "claude-3-5-sonnet-20240620",
  "processing": {
    "mode": "auto",
    "fallback_to_sync": true,
    "batch_size": 10,
    "delay_seconds": 60,
    "max_retries": 3,
    "worker_check_interval": 5,
    "queue_timeout": 30
  },
  "exclude_patterns": [
    "*.test.js",
    "vendor/*",
    "tmp/*"
  ]
}
```