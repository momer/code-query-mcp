"""Integration tests for the application layer with real components."""

import os
import tempfile
import shutil
import time
from unittest.mock import patch, Mock

from app import DocumentationService, JobStatus
from storage.sqlite_storage import CodeQueryServer
from analysis.analyzer import FileAnalyzer


class TestApplicationIntegration:
    """Integration tests using real components where possible."""
    
    def setup_method(self):
        """Set up test environment."""
        # Create temporary project directory
        self.project_root = tempfile.mkdtemp()
        
        # Create code-query directory
        os.makedirs(os.path.join(self.project_root, ".code-query"))
        
        # Create database path and directory
        self.db_dir = os.path.join(self.project_root, ".code-query")
        self.db_path = os.path.join(self.db_dir, "test.db")
        
        # Initialize storage with both db_path and db_dir
        self.storage = CodeQueryServer.from_db_path(db_path=self.db_path, db_dir=self.db_dir)
        
        # Storage needs to know the working directory
        self.storage.cwd = self.project_root
        
        # Create test files
        self._create_test_files()
        
    def teardown_method(self):
        """Clean up test environment."""
        shutil.rmtree(self.project_root)
        
    def _create_test_files(self):
        """Create test project structure."""
        # Create directories
        os.makedirs(os.path.join(self.project_root, "src"))
        os.makedirs(os.path.join(self.project_root, "tests"))
        
        # Create Python files
        with open(os.path.join(self.project_root, "main.py"), 'w') as f:
            f.write("""
def main():
    '''Main entry point.'''
    print("Hello World")

if __name__ == "__main__":
    main()
""")
        
        with open(os.path.join(self.project_root, "src", "utils.py"), 'w') as f:
            f.write("""
def add(a: int, b: int) -> int:
    '''Add two numbers.'''
    return a + b

def multiply(a: int, b: int) -> int:
    '''Multiply two numbers.'''
    return a * b
""")
        
        # Create config
        import json
        config = {
            "mainDatasetName": "test-project",
            "model": "sonnet"
        }
        with open(os.path.join(self.project_root, ".code-query", "config.json"), 'w') as f:
            json.dump(config, f)
            
    @patch('subprocess.run')
    def test_full_documentation_workflow(self, mock_run):
        """Test complete documentation workflow without actual Claude calls."""
        # Mock Claude responses
        claude_response = Mock()
        claude_response.returncode = 0
        claude_response.stdout = """
        This file contains utility functions:
        - add: Adds two numbers
        - multiply: Multiplies two numbers
        """
        mock_run.return_value = claude_response
        
        # Create service
        service = DocumentationService(self.project_root, self.storage)
        
        # Start documentation job (dataset will be created automatically)
        job = service.start_documentation_job(
            dataset_name="test-project",
            directory=".",
            batch_size=1  # One file per batch for easier testing
        )
        
        assert job is not None
        assert job.status == JobStatus.RUNNING
        assert job.total_files == 2  # main.py and src/utils.py
        
        # Verify job was persisted
        retrieved_job = service.get_job_status(job.job_id)
        assert retrieved_job is not None
        assert retrieved_job.job_id == job.job_id
        
        # Check progress
        progress = service.get_progress(job.job_id)
        assert progress["total_files"] == 2
        assert progress["status"] == "running"
        
    def test_job_persistence_across_instances(self):
        """Test that jobs persist across service instances."""
        # Create first service instance
        service1 = DocumentationService(self.project_root, self.storage)
        
        # Mock file discovery to return empty (to avoid Claude calls)
        with patch.object(service1.discovery, 'discover_files', return_value=[]):
            try:
                job = service1.start_documentation_job("test-project")
            except ValueError:
                # Expected - no files found
                pass
        
        # Create active job manually
        from app import DocumentationJob
        job = DocumentationJob(
            dataset_name="test-project",
            project_root=self.project_root,
            total_files=10,
            processed_files=3,
            status=JobStatus.RUNNING
        )
        service1.job_storage.create_job(job)
        service1.job_storage.start_job(job.job_id)
        
        # Create new service instance
        service2 = DocumentationService(self.project_root, self.storage)
        
        # Should be able to find the job
        active_jobs = service2.list_active_jobs()
        assert len(active_jobs) == 1
        assert active_jobs[0].job_id == job.job_id
        assert active_jobs[0].processed_files == 3
        
    @patch('subprocess.run')
    def test_job_cancellation(self, mock_run):
        """Test cancelling a running job."""
        # Mock Claude
        mock_run.return_value = Mock(returncode=0, stdout="Mock response")
        
        service = DocumentationService(self.project_root, self.storage)
        
        # Start job
        job = service.start_documentation_job("test-project")
        assert job.status == JobStatus.RUNNING
        
        # Cancel job
        success = service.cancel_job(job.job_id)
        assert success is True
        
        # Verify cancellation
        cancelled_job = service.get_job_status(job.job_id)
        assert cancelled_job.status == JobStatus.CANCELLED
        assert cancelled_job.completed_at is not None
        
        # Can't cancel again
        assert service.cancel_job(job.job_id) is False
        
    def test_file_discovery_integration(self):
        """Test that file discovery correctly finds project files."""
        service = DocumentationService(self.project_root, self.storage)
        
        # Test discovery
        files = service.discovery.discover_files()
        
        assert len(files) == 2
        assert "main.py" in files
        assert "src/utils.py" in files
        
        # Test with exclusions
        files_no_tests = service.discovery.discover_files(exclude_patterns=["src/*"])
        assert len(files_no_tests) == 1
        assert "main.py" in files_no_tests
        assert "src/utils.py" not in files_no_tests
        
    @patch('subprocess.run')
    def test_analyzer_integration(self, mock_run):
        """Test FileAnalyzer integration with storage."""
        # Mock Claude response
        mock_run.return_value = Mock(
            returncode=0,
            stdout="This is the main entry point of the application."
        )
        
        # Dataset will be created automatically by the storage layer
        
        # Create analyzer
        analyzer = FileAnalyzer(self.project_root, self.storage, model="sonnet")
        
        # Analyze file
        result = analyzer.analyze_and_document(
            filepath="main.py",
            dataset_name="test-project",
            commit_hash="abc123"
        )
        
        assert result["success"] is True
        assert result["filepath"] == "main.py"
        
        # Verify stored in database
        docs = self.storage.get_file_documentation("test-project", "main.py")
        assert docs is not None
        assert "main entry point" in docs["overview"]


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])