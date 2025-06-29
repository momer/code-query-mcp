import unittest
import tempfile
import os
import json
from unittest.mock import patch

import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from storage.config_manager import ConfigManager

class TestConfigLoading(unittest.TestCase):
    """Test suite for configuration management."""
    
    def setUp(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.config_path = os.path.join(self.temp_dir, '.code-query', 'config.json')
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
        self.config_manager = ConfigManager(self.config_path)
    
    def tearDown(self):
        """Clean up test environment."""
        import shutil
        shutil.rmtree(self.temp_dir)
    
    def test_create_default_config(self):
        """Test creating comprehensive default configuration with all expected fields."""
        self.config_manager.create_default_config()
        
        # Verify config file was created
        self.assertTrue(os.path.exists(self.config_path))
        
        # Load and validate all default config fields
        config = self.config_manager.load_config()
        
        # Test required fields exist and have valid values
        self.assertIsNotNone(config['dataset_name'])
        self.assertIsInstance(config['dataset_name'], str)
        self.assertGreater(len(config['dataset_name']), 0)
        
        # Test processing configuration structure
        self.assertIn('processing', config)
        self.assertIsInstance(config['processing'], dict)
        self.assertEqual(config['processing']['mode'], 'manual')
        self.assertIsInstance(config['processing'].get('fallback_to_sync'), bool)
        
        # Test model configuration
        if 'model' in config:
            self.assertIsInstance(config['model'], str)
            self.assertGreater(len(config['model']), 0)
        
        # Test exclude patterns if present
        if 'exclude_patterns' in config:
            self.assertIsInstance(config['exclude_patterns'], list)
            for pattern in config['exclude_patterns']:
                self.assertIsInstance(pattern, str)
        
        # Verify the config passes validation
        try:
            self.config_manager.validate_config(config)
        except ValueError as e:
            self.fail(f"Default config should pass validation but failed: {e}")
    
    def test_load_valid_config(self):
        """Test loading valid configuration with comprehensive field validation and default merging."""
        config_data = {
            'dataset_name': 'test-project',
            'model': 'claude-3-5-sonnet-20240620',
            'processing': {
                'mode': 'auto'
            },
            'exclude_patterns': ['*.test.js', 'temp/*']
        }
        
        with open(self.config_path, 'w') as f:
            json.dump(config_data, f)
        
        config = self.config_manager.load_config()
        
        # Verify all explicitly set fields are preserved
        self.assertEqual(config['dataset_name'], 'test-project')
        self.assertEqual(config['model'], 'claude-3-5-sonnet-20240620')
        self.assertEqual(config['processing']['mode'], 'auto')
        self.assertEqual(config['exclude_patterns'], ['*.test.js', 'temp/*'])
        
        # Verify defaults are properly merged for missing fields
        self.assertTrue(config['processing']['fallback_to_sync'],
                       "Default fallback_to_sync should be merged when not specified")
        
        # Verify the configuration structure is complete
        self.assertIsInstance(config['processing'], dict)
        self.assertIsInstance(config['exclude_patterns'], list)
        
        # Verify the loaded config passes validation
        try:
            self.config_manager.validate_config(config)
        except ValueError as e:
            self.fail(f"Valid config should pass validation but failed: {e}")
        
        # Test that types are correct
        self.assertIsInstance(config['dataset_name'], str)
        self.assertIsInstance(config['model'], str)
        self.assertIsInstance(config['processing']['mode'], str)
        self.assertIsInstance(config['processing']['fallback_to_sync'], bool)
    
    def test_validation_errors(self):
        """Test comprehensive configuration validation."""
        # Test missing required field - dataset_name
        with self.subTest("missing dataset_name"):
            with open(self.config_path, 'w') as f:
                json.dump({}, f)
            
            with self.assertRaises(ValueError) as ctx:
                self.config_manager.load_config()
            self.assertIn('dataset_name', str(ctx.exception))
        
        # Test empty dataset_name
        with self.subTest("empty dataset_name"):
            with open(self.config_path, 'w') as f:
                json.dump({'dataset_name': ''}, f)
            
            with self.assertRaises(ValueError) as ctx:
                self.config_manager.load_config()
            self.assertIn('dataset_name', str(ctx.exception))
        
        # Test None dataset_name
        with self.subTest("None dataset_name"):
            with open(self.config_path, 'w') as f:
                json.dump({'dataset_name': None}, f)
            
            with self.assertRaises(ValueError) as ctx:
                self.config_manager.load_config()
            self.assertIn('dataset_name', str(ctx.exception))
        
        # Test invalid processing mode
        with self.subTest("invalid processing mode"):
            with open(self.config_path, 'w') as f:
                json.dump({
                    'dataset_name': 'test',
                    'processing': {'mode': 'invalid'}
                }, f)
            
            with self.assertRaises(ValueError) as ctx:
                self.config_manager.load_config()
            self.assertIn('Invalid processing mode', str(ctx.exception))
        
        # Test processing mode with wrong type
        with self.subTest("processing mode not string"):
            with open(self.config_path, 'w') as f:
                json.dump({
                    'dataset_name': 'test',
                    'processing': {'mode': 123}
                }, f)
            
            with self.assertRaises(ValueError) as ctx:
                self.config_manager.load_config()
            self.assertIn('Invalid processing mode', str(ctx.exception))
        
        # Test batch_size validation
        with self.subTest("batch_size not integer"):
            with open(self.config_path, 'w') as f:
                json.dump({
                    'dataset_name': 'test',
                    'processing': {'batch_size': 'five'}
                }, f)
            
            with self.assertRaises(ValueError) as ctx:
                self.config_manager.load_config()
            self.assertIn('batch_size must be a positive integer', str(ctx.exception))
        
        with self.subTest("batch_size float"):
            with open(self.config_path, 'w') as f:
                json.dump({
                    'dataset_name': 'test',
                    'processing': {'batch_size': 5.5}
                }, f)
            
            with self.assertRaises(ValueError) as ctx:
                self.config_manager.load_config()
            self.assertIn('batch_size must be a positive integer', str(ctx.exception))
        
        with self.subTest("batch_size zero"):
            with open(self.config_path, 'w') as f:
                json.dump({
                    'dataset_name': 'test',
                    'processing': {'batch_size': 0}
                }, f)
            
            with self.assertRaises(ValueError) as ctx:
                self.config_manager.load_config()
            self.assertIn('batch_size must be a positive integer', str(ctx.exception))
        
        with self.subTest("batch_size negative"):
            with open(self.config_path, 'w') as f:
                json.dump({
                    'dataset_name': 'test',
                    'processing': {'batch_size': -5}
                }, f)
            
            with self.assertRaises(ValueError) as ctx:
                self.config_manager.load_config()
            self.assertIn('batch_size must be a positive integer', str(ctx.exception))
        
        # Test delay_seconds validation
        with self.subTest("delay_seconds not number"):
            with open(self.config_path, 'w') as f:
                json.dump({
                    'dataset_name': 'test',
                    'processing': {'delay_seconds': 'ten'}
                }, f)
            
            with self.assertRaises(ValueError) as ctx:
                self.config_manager.load_config()
            self.assertIn('delay_seconds must be non-negative', str(ctx.exception))
        
        with self.subTest("delay_seconds negative"):
            with open(self.config_path, 'w') as f:
                json.dump({
                    'dataset_name': 'test',
                    'processing': {'delay_seconds': -10}
                }, f)
            
            with self.assertRaises(ValueError) as ctx:
                self.config_manager.load_config()
            self.assertIn('delay_seconds must be non-negative', str(ctx.exception))
        
        with self.subTest("delay_seconds negative float"):
            with open(self.config_path, 'w') as f:
                json.dump({
                    'dataset_name': 'test',
                    'processing': {'delay_seconds': -10.5}
                }, f)
            
            with self.assertRaises(ValueError) as ctx:
                self.config_manager.load_config()
            self.assertIn('delay_seconds must be non-negative', str(ctx.exception))
        
        # Test max_retries validation
        with self.subTest("max_retries not integer"):
            with open(self.config_path, 'w') as f:
                json.dump({
                    'dataset_name': 'test',
                    'processing': {'max_retries': 2.5}
                }, f)
            
            with self.assertRaises(ValueError) as ctx:
                self.config_manager.load_config()
            self.assertIn('max_retries must be a non-negative integer', str(ctx.exception))
        
        with self.subTest("max_retries string"):
            with open(self.config_path, 'w') as f:
                json.dump({
                    'dataset_name': 'test',
                    'processing': {'max_retries': 'twice'}
                }, f)
            
            with self.assertRaises(ValueError) as ctx:
                self.config_manager.load_config()
            self.assertIn('max_retries must be a non-negative integer', str(ctx.exception))
        
        with self.subTest("max_retries negative"):
            with open(self.config_path, 'w') as f:
                json.dump({
                    'dataset_name': 'test',
                    'processing': {'max_retries': -1}
                }, f)
            
            with self.assertRaises(ValueError) as ctx:
                self.config_manager.load_config()
            self.assertIn('max_retries must be a non-negative integer', str(ctx.exception))
        
        # Test worker_check_interval validation
        with self.subTest("worker_check_interval not number"):
            with open(self.config_path, 'w') as f:
                json.dump({
                    'dataset_name': 'test',
                    'processing': {'worker_check_interval': 'fast'}
                }, f)
            
            with self.assertRaises(ValueError) as ctx:
                self.config_manager.load_config()
            self.assertIn('worker_check_interval must be a positive number', str(ctx.exception))
        
        with self.subTest("worker_check_interval zero"):
            with open(self.config_path, 'w') as f:
                json.dump({
                    'dataset_name': 'test',
                    'processing': {'worker_check_interval': 0}
                }, f)
            
            with self.assertRaises(ValueError) as ctx:
                self.config_manager.load_config()
            self.assertIn('worker_check_interval must be a positive number', str(ctx.exception))
        
        with self.subTest("worker_check_interval negative"):
            with open(self.config_path, 'w') as f:
                json.dump({
                    'dataset_name': 'test',
                    'processing': {'worker_check_interval': -5}
                }, f)
            
            with self.assertRaises(ValueError) as ctx:
                self.config_manager.load_config()
            self.assertIn('worker_check_interval must be a positive number', str(ctx.exception))
        
        with self.subTest("worker_check_interval negative float"):
            with open(self.config_path, 'w') as f:
                json.dump({
                    'dataset_name': 'test',
                    'processing': {'worker_check_interval': -0.5}
                }, f)
            
            with self.assertRaises(ValueError) as ctx:
                self.config_manager.load_config()
            self.assertIn('worker_check_interval must be a positive number', str(ctx.exception))
        
        # Test queue_timeout validation
        with self.subTest("queue_timeout not number"):
            with open(self.config_path, 'w') as f:
                json.dump({
                    'dataset_name': 'test',
                    'processing': {'queue_timeout': 'never'}
                }, f)
            
            with self.assertRaises(ValueError) as ctx:
                self.config_manager.load_config()
            self.assertIn('queue_timeout must be a non-negative number', str(ctx.exception))
        
        with self.subTest("queue_timeout negative"):
            with open(self.config_path, 'w') as f:
                json.dump({
                    'dataset_name': 'test',
                    'processing': {'queue_timeout': -30}
                }, f)
            
            with self.assertRaises(ValueError) as ctx:
                self.config_manager.load_config()
            self.assertIn('queue_timeout must be a non-negative number', str(ctx.exception))
        
        with self.subTest("queue_timeout negative float"):
            with open(self.config_path, 'w') as f:
                json.dump({
                    'dataset_name': 'test',
                    'processing': {'queue_timeout': -30.5}
                }, f)
            
            with self.assertRaises(ValueError) as ctx:
                self.config_manager.load_config()
            self.assertIn('queue_timeout must be a non-negative number', str(ctx.exception))
        
        # Test fallback_to_sync validation
        with self.subTest("fallback_to_sync not boolean"):
            with open(self.config_path, 'w') as f:
                json.dump({
                    'dataset_name': 'test',
                    'processing': {'fallback_to_sync': 'yes'}
                }, f)
            
            with self.assertRaises(ValueError) as ctx:
                self.config_manager.load_config()
            self.assertIn('fallback_to_sync must be a boolean', str(ctx.exception))
        
        with self.subTest("fallback_to_sync integer"):
            with open(self.config_path, 'w') as f:
                json.dump({
                    'dataset_name': 'test',
                    'processing': {'fallback_to_sync': 1}
                }, f)
            
            with self.assertRaises(ValueError) as ctx:
                self.config_manager.load_config()
            self.assertIn('fallback_to_sync must be a boolean', str(ctx.exception))
        
        with self.subTest("fallback_to_sync None"):
            with open(self.config_path, 'w') as f:
                json.dump({
                    'dataset_name': 'test',
                    'processing': {'fallback_to_sync': None}
                }, f)
            
            with self.assertRaises(ValueError) as ctx:
                self.config_manager.load_config()
            self.assertIn('fallback_to_sync must be a boolean', str(ctx.exception))
        
        # Test exclude_patterns validation
        with self.subTest("exclude_patterns not list"):
            with open(self.config_path, 'w') as f:
                json.dump({
                    'dataset_name': 'test',
                    'exclude_patterns': '*.test.js'
                }, f)
            
            with self.assertRaises(ValueError) as ctx:
                self.config_manager.load_config()
            self.assertIn('exclude_patterns must be a list', str(ctx.exception))
        
        with self.subTest("exclude_patterns dict"):
            with open(self.config_path, 'w') as f:
                json.dump({
                    'dataset_name': 'test',
                    'exclude_patterns': {'pattern': '*.test.js'}
                }, f)
            
            with self.assertRaises(ValueError) as ctx:
                self.config_manager.load_config()
            self.assertIn('exclude_patterns must be a list', str(ctx.exception))
        
        with self.subTest("exclude_patterns items not strings"):
            with open(self.config_path, 'w') as f:
                json.dump({
                    'dataset_name': 'test',
                    'exclude_patterns': ['*.test.js', 123, True]
                }, f)
            
            with self.assertRaises(ValueError) as ctx:
                self.config_manager.load_config()
            self.assertIn('All items in exclude_patterns must be strings', str(ctx.exception))
        
        with self.subTest("exclude_patterns with None item"):
            with open(self.config_path, 'w') as f:
                json.dump({
                    'dataset_name': 'test',
                    'exclude_patterns': ['*.test.js', None]
                }, f)
            
            with self.assertRaises(ValueError) as ctx:
                self.config_manager.load_config()
            self.assertIn('All items in exclude_patterns must be strings', str(ctx.exception))
        
        # Test model name validation
        with self.subTest("model name with invalid characters"):
            with open(self.config_path, 'w') as f:
                json.dump({
                    'dataset_name': 'test',
                    'model': 'claude@3.5#sonnet'
                }, f)
            
            with self.assertRaises(ValueError) as ctx:
                self.config_manager.load_config()
            self.assertIn('Invalid model name', str(ctx.exception))
            self.assertIn('alphanumeric characters, dots, dashes, and underscores', str(ctx.exception))
        
        with self.subTest("model name with spaces"):
            with open(self.config_path, 'w') as f:
                json.dump({
                    'dataset_name': 'test',
                    'model': 'claude 3.5 sonnet'
                }, f)
            
            with self.assertRaises(ValueError) as ctx:
                self.config_manager.load_config()
            self.assertIn('Invalid model name', str(ctx.exception))
            self.assertIn('alphanumeric characters, dots, dashes, and underscores', str(ctx.exception))
        
        with self.subTest("model name with special chars"):
            with open(self.config_path, 'w') as f:
                json.dump({
                    'dataset_name': 'test',
                    'model': 'claude/3.5\\sonnet'
                }, f)
            
            with self.assertRaises(ValueError) as ctx:
                self.config_manager.load_config()
            self.assertIn('Invalid model name', str(ctx.exception))
            self.assertIn('alphanumeric characters, dots, dashes, and underscores', str(ctx.exception))
        
        with self.subTest("model name too long"):
            with open(self.config_path, 'w') as f:
                json.dump({
                    'dataset_name': 'test',
                    'model': 'a' * 101  # 101 characters
                }, f)
            
            with self.assertRaises(ValueError) as ctx:
                self.config_manager.load_config()
            self.assertIn('Model name too long', str(ctx.exception))
            self.assertIn('100 characters or less', str(ctx.exception))
        
        with self.subTest("model name exactly 100 chars"):
            # This should pass - exactly at the limit
            with open(self.config_path, 'w') as f:
                json.dump({
                    'dataset_name': 'test',
                    'model': 'a' * 100  # 100 characters
                }, f)
            
            # Should not raise - exactly at limit is OK
            config = self.config_manager.load_config()
            self.assertEqual(len(config['model']), 100)
        
        # Test invalid JSON
        with self.subTest("invalid JSON syntax"):
            # Clear any cached config
            self.config_manager._config_cache = None
            self.config_manager._last_modified = None
            
            with open(self.config_path, 'w') as f:
                f.write('{"dataset_name": "test", invalid json}')
            
            with self.assertRaises(ValueError) as ctx:
                self.config_manager.load_config()
            self.assertIn('Invalid JSON', str(ctx.exception))
        
        # Test dataset_name type validation
        with self.subTest("dataset_name as number"):
            # Clear any cached config
            self.config_manager._config_cache = None
            self.config_manager._last_modified = None
            
            with open(self.config_path, 'w') as f:
                json.dump({'dataset_name': 123}, f)
            
            with self.assertRaises(ValueError) as ctx:
                self.config_manager.load_config()
            self.assertIn('must be a string', str(ctx.exception))
        
        with self.subTest("dataset_name as list"):
            # Clear any cached config
            self.config_manager._config_cache = None
            self.config_manager._last_modified = None
            
            with open(self.config_path, 'w') as f:
                json.dump({'dataset_name': ['test']}, f)
            
            with self.assertRaises(ValueError) as ctx:
                self.config_manager.load_config()
            self.assertIn('must be a string', str(ctx.exception))
        
        # Test whitespace-only dataset_name
        with self.subTest("dataset_name whitespace only"):
            # Clear any cached config
            self.config_manager._config_cache = None
            self.config_manager._last_modified = None
            
            with open(self.config_path, 'w') as f:
                json.dump({'dataset_name': '   \t\n  '}, f)
            
            with self.assertRaises(ValueError) as ctx:
                self.config_manager.load_config()
            self.assertIn('cannot be empty', str(ctx.exception))
    
    def test_deep_merge(self):
        """Test deep merging of configurations."""
        # Partial config
        with open(self.config_path, 'w') as f:
            json.dump({
                'dataset_name': 'test',
                'processing': {
                    'batch_size': 10
                }
            }, f)
        
        config = self.config_manager.load_config()
        
        # Should have user value
        self.assertEqual(config['processing']['batch_size'], 10)
        # Should have defaults for missing values
        self.assertEqual(config['processing']['mode'], 'manual')
        self.assertTrue(config['processing']['fallback_to_sync'])
    
    def test_atomic_save(self):
        """Test atomic configuration saves."""
        config = {
            'dataset_name': 'test',
            'processing': {'mode': 'manual'}
        }
        
        # Save normally first
        self.config_manager.save_config(config)
        
        # Mock os.replace to simulate failure
        with patch('os.replace') as mock_replace:
            mock_replace.side_effect = OSError("Simulated failure")
            
            with self.assertRaises(OSError):
                config['dataset_name'] = 'changed'
                self.config_manager.save_config(config)
        
        # Original file should be unchanged
        loaded_config = self.config_manager.load_config()
        self.assertEqual(loaded_config['dataset_name'], 'test')
    
    def test_update_processing_mode(self):
        """Test updating processing mode."""
        # Create initial config
        self.config_manager.create_default_config()
        
        # Update mode with valid value
        self.config_manager.update_processing_mode('auto')
        
        # Verify update
        config = self.config_manager.load_config()
        self.assertEqual(config['processing']['mode'], 'auto')
        
        # Test invalid mode
        with self.assertRaises(ValueError) as ctx:
            self.config_manager.update_processing_mode('invalid')
        self.assertIn('Invalid processing mode', str(ctx.exception))
        
        # Test mode with wrong type
        with self.assertRaises(ValueError) as ctx:
            self.config_manager.update_processing_mode(123)
        self.assertIn('Invalid processing mode', str(ctx.exception))
    
    def test_validate_config_schema(self):
        """Test schema validation."""
        valid_config = {
            'dataset_name': 'test',
            'model': 'claude-3-5-sonnet-20240620',
            'processing': {
                'mode': 'manual',
                'fallback_to_sync': True,
                'batch_size': 5,
                'retry_attempts': 2,
                'retry_delay': 60
            }
        }
        
        # Should not raise
        self.config_manager.validate_config(valid_config)
        
        # Test invalid types
        invalid_configs = [
            # Invalid mode
            {**valid_config, 'processing': {**valid_config['processing'], 'mode': 123}},
            # Invalid batch_size
            {**valid_config, 'processing': {**valid_config['processing'], 'batch_size': 'five'}},
            # Invalid fallback_to_sync
            {**valid_config, 'processing': {**valid_config['processing'], 'fallback_to_sync': 'yes'}},
        ]
        
        for invalid_config in invalid_configs:
            with self.assertRaises(ValueError):
                self.config_manager.validate_config(invalid_config)
    
    def test_environment_variable_override(self):
        """Test environment variable overrides."""
        from storage.config_manager import load_config_with_env_override
        
        # Create basic config
        with open(self.config_path, 'w') as f:
            json.dump({
                'dataset_name': 'test',
                'model': 'original-model',
                'processing': {
                    'mode': 'manual',
                    'batch_size': 5
                }
            }, f)
        
        # Test valid model override
        with self.subTest("valid model override"):
            with patch.dict(os.environ, {'CODEQUERY_MODEL': 'claude-3-haiku-20240307'}):
                config = load_config_with_env_override(self.config_manager)
                self.assertEqual(config['model'], 'claude-3-haiku-20240307')
        
        # Test valid processing mode override
        with self.subTest("valid processing mode override"):
            with patch.dict(os.environ, {'CODEQUERY_PROCESSING_MODE': 'auto'}):
                config = load_config_with_env_override(self.config_manager)
                self.assertEqual(config['processing']['mode'], 'auto')
        
        # Test valid batch size override
        with self.subTest("valid batch size override"):
            with patch.dict(os.environ, {'CODEQUERY_BATCH_SIZE': '10'}):
                config = load_config_with_env_override(self.config_manager)
                self.assertEqual(config['processing']['batch_size'], 10)
        
        # Test invalid batch size - not a number
        with self.subTest("invalid batch size - not a number"):
            with patch.dict(os.environ, {'CODEQUERY_BATCH_SIZE': 'five'}):
                with self.assertRaises(ValueError) as ctx:
                    load_config_with_env_override(self.config_manager)
                self.assertIn('Invalid value for CODEQUERY_BATCH_SIZE', str(ctx.exception))
        
        # Test invalid batch size - zero
        with self.subTest("invalid batch size - zero"):
            with patch.dict(os.environ, {'CODEQUERY_BATCH_SIZE': '0'}):
                with self.assertRaises(ValueError) as ctx:
                    load_config_with_env_override(self.config_manager)
                self.assertIn('Invalid value for CODEQUERY_BATCH_SIZE', str(ctx.exception))
                self.assertIn('must be a positive integer', str(ctx.exception))
        
        # Test invalid batch size - negative
        with self.subTest("invalid batch size - negative"):
            with patch.dict(os.environ, {'CODEQUERY_BATCH_SIZE': '-5'}):
                with self.assertRaises(ValueError) as ctx:
                    load_config_with_env_override(self.config_manager)
                self.assertIn('Invalid value for CODEQUERY_BATCH_SIZE', str(ctx.exception))
                self.assertIn('must be a positive integer', str(ctx.exception))
        
        # Test invalid processing mode via env var
        with self.subTest("invalid processing mode via env var"):
            with patch.dict(os.environ, {'CODEQUERY_PROCESSING_MODE': 'invalid'}):
                with self.assertRaises(ValueError) as ctx:
                    load_config_with_env_override(self.config_manager)
                self.assertIn('Invalid processing mode', str(ctx.exception))
        
        # Test invalid model via env var with special characters
        with self.subTest("invalid model via env var"):
            with patch.dict(os.environ, {'CODEQUERY_MODEL': 'claude@3.5#sonnet'}):
                with self.assertRaises(ValueError) as ctx:
                    load_config_with_env_override(self.config_manager)
                self.assertIn('Invalid model name', str(ctx.exception))
                self.assertIn('alphanumeric characters, dots, dashes, and underscores', str(ctx.exception))
        
        # Test multiple env overrides together
        with self.subTest("multiple valid env overrides"):
            with patch.dict(os.environ, {
                'CODEQUERY_MODEL': 'custom-model-123',
                'CODEQUERY_PROCESSING_MODE': 'auto',
                'CODEQUERY_BATCH_SIZE': '20'
            }):
                config = load_config_with_env_override(self.config_manager)
                self.assertEqual(config['model'], 'custom-model-123')
                self.assertEqual(config['processing']['mode'], 'auto')
                self.assertEqual(config['processing']['batch_size'], 20)
    
    def test_config_file_permissions(self):
        """Test that config file is created with appropriate permissions."""
        self.config_manager.create_default_config()
        
        # Check file permissions (current implementation uses default umask)
        stat_info = os.stat(self.config_path)
        mode = stat_info.st_mode
        
        # Check that group and others don't have write permission (minimum security)
        # Note: ConfigManager currently doesn't set restrictive permissions explicitly
        # This could be improved to set 0o600 for better security
        self.assertEqual(mode & 0o022, 0)
    
    def test_validate_config_file(self):
        """Test config file validation method."""
        # Test with valid config
        self.config_manager.create_default_config()
        issues = self.config_manager.validate_config_file()
        self.assertEqual(len(issues), 0)
        
        # Test with unknown top-level fields (these will be preserved in loaded config)
        # Clear cache first
        self.config_manager._config_cache = None
        self.config_manager._last_modified = None
        
        with open(self.config_path, 'w') as f:
            json.dump({
                'dataset_name': 'test',
                'unknown_field': 'value',
                'another_unknown': 123,
                'model': 'claude-3-5-sonnet-20240620',
                'processing': {'mode': 'manual'}
            }, f)
        
        issues = self.config_manager.validate_config_file()
        self.assertGreater(len(issues), 0)
        self.assertTrue(any('unknown_field' in issue for issue in issues))
        self.assertTrue(any('another_unknown' in issue for issue in issues))
        
        # Test with unknown processing fields
        # Clear cache first
        self.config_manager._config_cache = None
        self.config_manager._last_modified = None
        
        with open(self.config_path, 'w') as f:
            json.dump({
                'dataset_name': 'test',
                'processing': {
                    'mode': 'manual',
                    'unknown_processing_field': 'value',
                    'another_unknown_processing': 123
                }
            }, f)
        
        issues = self.config_manager.validate_config_file()
        self.assertGreater(len(issues), 0)
        self.assertTrue(any('unknown_processing_field' in issue for issue in issues))
        
        # Test with completely invalid config
        # Clear cache first
        self.config_manager._config_cache = None
        self.config_manager._last_modified = None
        
        with open(self.config_path, 'w') as f:
            f.write('not valid json at all')
        
        issues = self.config_manager.validate_config_file()
        self.assertGreater(len(issues), 0)
        self.assertTrue(any('Error loading configuration' in issue for issue in issues))
        
        # Test deprecated field detection - this test shows that validate_config_file
        # won't detect deprecated fields after load_config processes them
        # This is expected behavior as load_config migrates the config


    def test_config_migrator(self):
        """Test configuration migration."""
        from storage.config_manager import ConfigMigrator
        
        # Test V0 to V1 migration only
        v0_config = {
            'dataset_name': 'test',
            'model': 'claude-3-5-sonnet-20240620'
        }
        migrated_v1 = ConfigMigrator._migrate_v0_to_v1(v0_config.copy())
        self.assertIn('auto_process', migrated_v1)
        self.assertFalse(migrated_v1['auto_process'])
        
        # Test full migration from V0 (goes to V2)
        migrated_full = ConfigMigrator.migrate_config(v0_config, from_version=0)
        self.assertNotIn('auto_process', migrated_full)  # Should be removed in V2
        self.assertIn('processing', migrated_full)
        self.assertEqual(migrated_full['processing']['mode'], 'manual')
        
        # Test V1 to V2 migration
        v1_config = {
            'dataset_name': 'test',
            'auto_process': True,
            'model': 'claude-3-5-sonnet-20240620'
        }
        migrated = ConfigMigrator.migrate_config(v1_config, from_version=1)
        self.assertNotIn('auto_process', migrated)
        self.assertIn('processing', migrated)
        self.assertEqual(migrated['processing']['mode'], 'auto')
        
        # Test auto-detection with V1 config
        v1_config_auto = {
            'dataset_name': 'test',
            'auto_process': False
        }
        migrated = ConfigMigrator.migrate_config(v1_config_auto)
        self.assertEqual(migrated['processing']['mode'], 'manual')
        
        # Test already migrated V2 config
        v2_config = {
            'dataset_name': 'test',
            'processing': {'mode': 'auto'}
        }
        migrated = ConfigMigrator.migrate_config(v2_config)
        self.assertEqual(migrated['processing']['mode'], 'auto')
        
        # Test version detection on original configs
        v0_original = {
            'dataset_name': 'test',
            'model': 'claude-3-5-sonnet-20240620'
        }
        v1_original = {
            'dataset_name': 'test',
            'auto_process': True,
            'model': 'claude-3-5-sonnet-20240620'
        }
        v2_original = {
            'dataset_name': 'test',
            'processing': {'mode': 'auto'}
        }
        
        self.assertEqual(ConfigMigrator._detect_version(v0_original), 0)
        self.assertEqual(ConfigMigrator._detect_version(v1_original), 1)  
        self.assertEqual(ConfigMigrator._detect_version(v2_original), 2)


if __name__ == '__main__':
    unittest.main()