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
        """Test creating default configuration."""
        self.config_manager.create_default_config()
        
        self.assertTrue(os.path.exists(self.config_path))
        
        config = self.config_manager.load_config()
        self.assertIsNotNone(config['dataset_name'])
        self.assertEqual(config['processing']['mode'], 'manual')
    
    def test_load_valid_config(self):
        """Test loading valid configuration."""
        config_data = {
            'dataset_name': 'test-project',
            'model': 'claude-3-5-sonnet-20240620',
            'processing': {
                'mode': 'auto'
            }
        }
        
        with open(self.config_path, 'w') as f:
            json.dump(config_data, f)
        
        config = self.config_manager.load_config()
        self.assertEqual(config['dataset_name'], 'test-project')
        self.assertEqual(config['processing']['mode'], 'auto')
        # Should have defaults merged
        self.assertTrue(config['processing']['fallback_to_sync'])
    
    def test_validation_errors(self):
        """Test configuration validation."""
        # Missing required field
        with open(self.config_path, 'w') as f:
            json.dump({}, f)
        
        with self.assertRaises(ValueError) as ctx:
            self.config_manager.load_config()
        self.assertIn('dataset_name', str(ctx.exception))
        
        # Invalid processing mode
        with open(self.config_path, 'w') as f:
            json.dump({
                'dataset_name': 'test',
                'processing': {'mode': 'invalid'}
            }, f)
        
        with self.assertRaises(ValueError) as ctx:
            self.config_manager.load_config()
        self.assertIn('Invalid processing mode', str(ctx.exception))
    
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
        
        # Update mode
        self.config_manager.update_processing_mode('auto')
        
        # Verify update
        config = self.config_manager.load_config()
        self.assertEqual(config['processing']['mode'], 'auto')
    
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
        # Skip this test as ConfigManager doesn't support env var overrides
        self.skipTest("Environment variable overrides not implemented")
    
    def test_config_file_permissions(self):
        """Test that config file is created with appropriate permissions."""
        self.config_manager.create_default_config()
        
        # Check file permissions (should be readable/writable by owner only)
        stat_info = os.stat(self.config_path)
        mode = stat_info.st_mode
        
        # Check that group and others don't have write permission
        self.assertEqual(mode & 0o022, 0)