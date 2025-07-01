"""Tests for SearchService with query complexity analysis."""

import unittest
from unittest.mock import Mock, patch, MagicMock
from search.search_service import SearchService, SearchConfig, SearchMode
from search.query_analyzer import QueryComplexityAnalyzer, ComplexityLevel
from search.models import FileMetadata, SearchResult


class TestSearchServiceComplexity(unittest.TestCase):
    """Test SearchService with query complexity analysis enabled."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Mock storage backend
        self.mock_storage = Mock()
        self.mock_storage.search_files.return_value = []
        self.mock_storage.search_full_content.return_value = []
        
        # Create service with complexity analysis enabled
        self.config = SearchConfig(
            enable_complexity_analysis=True,
            enable_fallback=False,  # Disable for simpler testing
            enable_progressive_search=False,
            max_query_terms=10,  # Low limit for testing
            max_query_cost=20.0  # Low limit for testing
        )
        
        self.service = SearchService(
            storage_backend=self.mock_storage,
            default_config=self.config
        )
    
    def test_simple_query_passes(self):
        """Test that simple queries pass complexity analysis."""
        # Set up mock to return results
        self.mock_storage.search_files.return_value = [
            FileMetadata(
                file_id=1,
                file_path="/test.py",
                file_name="test.py",
                file_extension=".py",
                file_size=100,
                last_modified="2024-01-01",
                content_hash="abc123",
                dataset_id="test",
                overview="Test file",
                language="python",
                functions=["test_func"],
                exports=[]
            )
        ]
        
        # Simple query should pass
        results = self.service.search_metadata("simple test", "test_dataset")
        
        # Should call storage
        self.mock_storage.search_files.assert_called()
        self.assertEqual(len(results), 1)
    
    def test_complex_query_blocked(self):
        """Test that overly complex queries are blocked."""
        # Query with too many terms
        complex_query = " ".join([f"term{i}" for i in range(20)])
        
        results = self.service.search_metadata(complex_query, "test_dataset")
        
        # Should not call storage
        self.mock_storage.search_files.assert_not_called()
        self.assertEqual(len(results), 0)
    
    def test_complexity_warnings_logged(self):
        """Test that complexity warnings are logged."""
        # Query with many operators approaching cost limit
        query = "a* AND b* OR c* AND d* OR e*"
        
        with patch('search.search_service.logger') as mock_logger:
            self.service.search_metadata(query, "test_dataset")
            
            # Should log warning about complexity
            # Check either info or warning was called
            if mock_logger.info.called:
                info_call = mock_logger.info.call_args[0][0]
                self.assertIn("complexity", info_call.lower())
            else:
                # If cost is too high, it logs a warning instead
                mock_logger.warning.assert_called()
    
    def test_custom_analyzer_config(self):
        """Test using custom analyzer configuration."""
        # The analyzer is created fresh in search_metadata, not using the one passed in constructor
        # So we need to adjust the config instead
        config = SearchConfig(
            enable_complexity_analysis=True,
            enable_fallback=False,
            enable_progressive_search=False,
            max_query_terms=3,  # Low limit
            max_query_cost=5.0  # Low limit
        )
        
        service = SearchService(
            storage_backend=self.mock_storage,
            default_config=config
        )
        
        # Query with 4 terms should be blocked
        results = service.search_metadata("one two three four", "test_dataset")
        self.assertEqual(len(results), 0)
        self.mock_storage.search_files.assert_not_called()
    
    def test_complexity_analysis_disabled(self):
        """Test that complex queries pass when analysis is disabled."""
        # Disable complexity analysis AND sanitization
        config = SearchConfig(
            enable_complexity_analysis=False,
            enable_query_sanitization=False,  # Also disable sanitization
            enable_fallback=False,
            enable_progressive_search=False
        )
        
        service = SearchService(
            storage_backend=self.mock_storage,
            default_config=config
        )
        
        # Complex query should pass through
        complex_query = " ".join([f"term{i}" for i in range(100)])
        service.search_metadata(complex_query, "test_dataset")
        
        # Should call storage
        self.mock_storage.search_files.assert_called()
    
    def test_content_search_complexity(self):
        """Test complexity analysis for content search."""
        # Complex query for content search
        complex_query = " ".join([f"term{i}" for i in range(20)])
        
        results = self.service.search_content(complex_query, "test_dataset")
        
        # Should not call storage
        self.mock_storage.search_full_content.assert_not_called()
        self.assertEqual(len(results), 0)
    
    def test_unified_search_complexity(self):
        """Test complexity analysis for unified search."""
        # Complex query
        complex_query = "(" * 10 + "test" + ")" * 10
        
        results = self.service.search(complex_query, "test_dataset")
        
        # Should not call storage methods
        self.mock_storage.search_files.assert_not_called()
        self.mock_storage.search_full_content.assert_not_called()
        self.assertEqual(len(results), 0)
    
    def test_wildcard_complexity(self):
        """Test that excessive wildcards trigger complexity limits."""
        # Many wildcards
        wildcard_query = "a* b* c* d* e* f* g* h* i* j* k*"
        
        with patch('search.search_service.logger') as mock_logger:
            results = self.service.search_metadata(wildcard_query, "test_dataset")
            
            # Should be blocked due to high cost
            self.assertEqual(len(results), 0)
            mock_logger.warning.assert_called()
    
    def test_deep_nesting_complexity(self):
        """Test that deep nesting triggers complexity limits."""
        # Deep nesting
        nested_query = "(" * 6 + "test" + ")" * 6
        
        results = self.service.search_metadata(nested_query, "test_dataset")
        
        # Should be blocked due to nesting depth
        self.assertEqual(len(results), 0)
        self.mock_storage.search_files.assert_not_called()


if __name__ == '__main__':
    unittest.main()