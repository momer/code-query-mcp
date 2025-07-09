"""High-level orchestration service for documentation workflows."""

import os
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
import logging

from storage.sqlite_storage import CodeQueryServer
from .job_models import DocumentationJob, JobStatus
from .job_storage import JobStorage
from .discovery import FileDiscoveryService
from tasks import process_documentation_batch, get_project_config

logger = logging.getLogger(__name__)


class DocumentationService:
    """
    Central orchestrator for documentation workflows.
    
    Responsibilities:
    - Job lifecycle management (create, resume, cancel)
    - File discovery coordination
    - Batch submission to Huey
    - Progress tracking and reporting
    """
    
    def __init__(self, project_root: str, storage: CodeQueryServer):
        """
        Initialize the documentation service.
        
        Args:
            project_root: Absolute path to project root
            storage: Storage backend instance
        """
        self.project_root = os.path.abspath(project_root)
        self.storage = storage
        self.job_storage = JobStorage(storage.db_path)
        self.discovery = FileDiscoveryService(project_root)
        
    def start_documentation_job(self,
                              dataset_name: str,
                              directory: str = ".",
                              exclude_patterns: Optional[List[str]] = None,
                              batch_size: int = 20,
                              model: Optional[str] = None) -> DocumentationJob:
        """
        Start a new documentation job.
        
        Args:
            dataset_name: Dataset to update
            directory: Directory to document (relative to project root)
            exclude_patterns: Additional patterns to exclude
            batch_size: Files per batch for Huey tasks
            model: Optional model override
            
        Returns:
            DocumentationJob instance
            
        Raises:
            ValueError: If no files found or dataset invalid
        """
        # Discover files
        files = self.discovery.discover_files(directory, exclude_patterns)
        
        if not files:
            raise ValueError(f"No code files found in {directory}")
        
        # Get model from config if not specified
        if not model:
            config = get_project_config(self.project_root)
            model = config.get('model', 'sonnet')
        
        # Create job record
        job = DocumentationJob(
            dataset_name=dataset_name,
            project_root=self.project_root,
            total_files=len(files),
            file_filters=exclude_patterns,
            options={
                'directory': directory,
                'batch_size': batch_size,
                'model': model
            }
        )
        
        # Save to database
        job = self.job_storage.create_job(job)
        
        # Atomically start the job
        if self.job_storage.start_job(job.job_id):
            job.status = JobStatus.RUNNING
            job.started_at = datetime.now(timezone.utc)
            
            # Submit files for processing
            self._submit_files_for_job(job, files)
            
            logger.info(f"Started documentation job {job.job_id} with {len(files)} files")
        else:
            logger.error(f"Failed to start job {job.job_id}")
            job.status = JobStatus.FAILED
            job.error_message = "Failed to transition job to RUNNING state"
            self.job_storage.update_job(job)
        
        return job
    
    def resume_job(self, job_id: str) -> Optional[DocumentationJob]:
        """
        Resume an interrupted job by processing remaining files and files that have changed.
        
        Args:
            job_id: ID of job to resume
            
        Returns:
            Updated job or None if job cannot be resumed
        """
        # Get job from storage
        job = self.job_storage.get_job(job_id)
        
        if not job:
            logger.warning(f"Job {job_id} not found")
            return None
            
        if not job.can_resume:
            logger.warning(f"Job {job_id} is in terminal state {job.status}, cannot resume")
            return None
        
        # Get processed files with their commit hashes
        processed_file_details = self.job_storage.get_processed_file_details_for_job(job_id)
        logger.info(f"Job {job_id} has {len(processed_file_details)} already processed files")
        
        # Discover all files with current commit hashes
        directory = job.options.get('directory', '.')
        current_files_info = self.discovery.get_files_with_commit_hashes(directory, job.file_filters)
        
        # Determine which files need processing
        remaining_files_info = []
        for file_info in current_files_info:
            filepath = file_info['filepath']
            current_hash = file_info['commit_hash']
            
            # Check if file was processed before
            last_processed_hash = processed_file_details.get(filepath)
            
            if last_processed_hash is None:
                # Never processed
                logger.debug(f"File {filepath} was never processed")
                remaining_files_info.append(file_info)
            elif last_processed_hash != current_hash:
                # File has changed since last processing
                logger.info(f"File {filepath} has changed (was: {last_processed_hash}, now: {current_hash})")
                remaining_files_info.append(file_info)
            # else: File unchanged, skip
        
        if not remaining_files_info:
            # Job is actually complete
            logger.info(f"Job {job_id} has no remaining or changed files, marking as complete")
            job.status = JobStatus.COMPLETED
            job.completed_at = datetime.now(timezone.utc)
            job.processed_files = len(processed_file_details)
            self.job_storage.update_job(job)
            return job
        
        # Update job status if needed
        if job.status == JobStatus.CREATED:
            if not self.job_storage.start_job(job_id):
                job.status = JobStatus.FAILED
                job.error_message = "Failed to start job during resume"
                self.job_storage.update_job(job)
                return job
            job.status = JobStatus.RUNNING
            job.started_at = datetime.now(timezone.utc)
        
        # Submit remaining files (now with commit hash info)
        logger.info(f"Resuming job {job_id} with {len(remaining_files_info)} files (new or changed)")
        self._submit_files_for_job_with_info(job, remaining_files_info)
        
        return job
    
    def cancel_job(self, job_id: str) -> bool:
        """
        Cancel a running job.
        
        Args:
            job_id: ID of job to cancel
            
        Returns:
            True if cancelled, False otherwise
        """
        success = self.job_storage.cancel_job(job_id)
        if success:
            logger.info(f"Successfully cancelled job {job_id}")
        else:
            logger.warning(f"Failed to cancel job {job_id}")
        return success
    
    def get_job_status(self, job_id: str) -> Optional[DocumentationJob]:
        """
        Get current status of a job.
        
        Args:
            job_id: ID of job to check
            
        Returns:
            Job instance or None if not found
        """
        return self.job_storage.get_job(job_id)
    
    def list_active_jobs(self) -> List[DocumentationJob]:
        """
        List all active (non-terminal) jobs.
        
        Returns:
            List of active DocumentationJob instances
        """
        return self.job_storage.get_active_jobs()
    
    def list_jobs_for_dataset(self, dataset_name: str) -> List[DocumentationJob]:
        """
        List all jobs for a specific dataset.
        
        Args:
            dataset_name: Dataset to filter by
            
        Returns:
            List of DocumentationJob instances
        """
        return self.job_storage.list_jobs(dataset_name=dataset_name)
    
    def cleanup_old_jobs(self, days: int = 30) -> int:
        """
        Remove completed jobs older than specified days.
        
        Args:
            days: Age threshold in days
            
        Returns:
            Number of jobs removed
        """
        count = self.job_storage.cleanup_old_jobs(days)
        logger.info(f"Cleaned up {count} old jobs")
        return count
    
    def _submit_files_for_job(self, job: DocumentationJob, files: List[str]):
        """
        Submit files to Huey for processing.
        
        Args:
            job: Job to process files for
            files: List of relative file paths
        """
        # Use efficient method to get all files with commit hashes
        file_info_list = self.discovery.get_files_with_commit_hashes(
            directory=job.options.get('directory', '.'),
            exclude_patterns=job.file_filters
        )
        
        # Filter to only the requested files
        files_set = set(files)
        file_info_list = [info for info in file_info_list if info['filepath'] in files_set]
        
        self._submit_files_for_job_with_info(job, file_info_list)
    
    def _submit_files_for_job_with_info(self, job: DocumentationJob, file_info_list: List[Dict[str, str]]):
        """
        Submit files with commit info to Huey for processing.
        
        Args:
            job: Job to process files for
            file_info_list: List of dicts with 'filepath' and 'commit_hash' keys
        """
        batch_size = job.options.get('batch_size', 20)
        
        # Create batches
        batches = [
            file_info_list[i:i+batch_size] 
            for i in range(0, len(file_info_list), batch_size)
        ]
        
        # Submit each batch to Huey
        logger.info(f"Submitting {len(batches)} batches for job {job.job_id}")
        
        for i, batch in enumerate(batches):
            result = process_documentation_batch(
                files=batch,
                dataset_name=job.dataset_name,
                project_root=job.project_root,
                job_id=job.job_id
            )
            logger.debug(f"Submitted batch {i+1}/{len(batches)}: {result}")
    
    def get_progress(self, job_id: str) -> Dict[str, Any]:
        """
        Get detailed progress information for a job.
        
        Args:
            job_id: ID of job to check
            
        Returns:
            Dict with progress details
        """
        job = self.job_storage.get_job(job_id)
        if not job:
            return {"error": "Job not found"}
        
        return {
            "job_id": job.job_id,
            "status": job.status.value,
            "total_files": job.total_files,
            "processed_files": job.processed_files,
            "failed_files": job.failed_files,
            "progress_percentage": job.progress_percentage(),
            "is_complete": job.is_terminal,
            "error_message": job.error_message
        }