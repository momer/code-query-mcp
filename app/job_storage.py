"""Storage layer for documentation jobs."""

import sqlite3
import json
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from contextlib import contextmanager
import logging

from .job_models import DocumentationJob, ProcessedFile, JobStatus

logger = logging.getLogger(__name__)


class JobStorage:
    """
    Handles persistent storage of documentation jobs.
    Uses the same SQLite database as the main storage but with separate tables.
    """
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_schema()
    
    def _init_schema(self):
        """Initialize job-related tables if they don't exist."""
        with self._get_connection() as conn:
            # Jobs table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS documentation_jobs (
                    job_id TEXT PRIMARY KEY,
                    dataset_name TEXT NOT NULL,
                    project_root TEXT NOT NULL,
                    status TEXT NOT NULL,
                    total_files INTEGER DEFAULT 0,
                    processed_files INTEGER DEFAULT 0,
                    failed_files INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    error_message TEXT,
                    file_filters TEXT,  -- JSON array
                    options TEXT,       -- JSON object
                    UNIQUE(job_id)
                )
            """)
            
            # Processed files table for job-specific tracking
            conn.execute("""
                CREATE TABLE IF NOT EXISTS job_processed_files (
                    job_id TEXT NOT NULL,
                    filepath TEXT NOT NULL,
                    processed_at TEXT NOT NULL,
                    success BOOLEAN NOT NULL,
                    error_message TEXT,
                    huey_task_id TEXT,
                    commit_hash TEXT,  -- Track commit hash at time of processing
                    PRIMARY KEY (job_id, filepath),
                    FOREIGN KEY (job_id) REFERENCES documentation_jobs(job_id)
                )
            """)
            
            # Create indexes
            conn.execute("CREATE INDEX IF NOT EXISTS idx_job_status ON documentation_jobs(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_job_dataset ON documentation_jobs(dataset_name)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_processed_job ON job_processed_files(job_id)")
            
            conn.commit()
    
    @contextmanager
    def _get_connection(self):
        """Get database connection with proper error handling."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    
    def create_job(self, job: DocumentationJob) -> DocumentationJob:
        """Create a new job in the database."""
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO documentation_jobs (
                    job_id, dataset_name, project_root, status, 
                    total_files, processed_files, failed_files,
                    created_at, started_at, completed_at, error_message,
                    file_filters, options
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                job.job_id,
                job.dataset_name,
                job.project_root,
                job.status.value,
                job.total_files,
                job.processed_files,
                job.failed_files,
                job.created_at.isoformat(),
                job.started_at.isoformat() if job.started_at else None,
                job.completed_at.isoformat() if job.completed_at else None,
                job.error_message,
                json.dumps(job.file_filters) if job.file_filters else None,
                json.dumps(job.options) if job.options else None
            ))
            conn.commit()
            logger.info(f"Created job {job.job_id} for dataset {job.dataset_name}")
        return job
    
    def get_job(self, job_id: str) -> Optional[DocumentationJob]:
        """Get a job by ID."""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM documentation_jobs WHERE job_id = ?", 
                (job_id,)
            ).fetchone()
            
            if not row:
                return None
                
            return self._row_to_job(row)
    
    def update_job(self, job: DocumentationJob) -> DocumentationJob:
        """Update an existing job."""
        with self._get_connection() as conn:
            conn.execute("""
                UPDATE documentation_jobs 
                SET status = ?, processed_files = ?, failed_files = ?,
                    started_at = ?, completed_at = ?, error_message = ?
                WHERE job_id = ?
            """, (
                job.status.value,
                job.processed_files,
                job.failed_files,
                job.started_at.isoformat() if job.started_at else None,
                job.completed_at.isoformat() if job.completed_at else None,
                job.error_message,
                job.job_id
            ))
            conn.commit()
        return job
    
    def start_job(self, job_id: str) -> bool:
        """Atomically start a job (transition from CREATED to RUNNING)."""
        with self._get_connection() as conn:
            # Use a transaction to ensure atomicity
            cursor = conn.cursor()
            try:
                # Check current status
                current = cursor.execute(
                    "SELECT status FROM documentation_jobs WHERE job_id = ?",
                    (job_id,)
                ).fetchone()
                
                if not current or current['status'] != JobStatus.CREATED.value:
                    return False
                
                # Update to running
                cursor.execute("""
                    UPDATE documentation_jobs 
                    SET status = ?, started_at = ?
                    WHERE job_id = ? AND status = ?
                """, (
                    JobStatus.RUNNING.value,
                    datetime.now(timezone.utc).isoformat(),
                    job_id,
                    JobStatus.CREATED.value
                ))
                
                conn.commit()
                return cursor.rowcount > 0
                
            except Exception:
                conn.rollback()
                raise
    
    def list_jobs(self, dataset_name: Optional[str] = None, 
                  status: Optional[JobStatus] = None) -> List[DocumentationJob]:
        """List jobs with optional filtering."""
        query = "SELECT * FROM documentation_jobs WHERE 1=1"
        params = []
        
        if dataset_name:
            query += " AND dataset_name = ?"
            params.append(dataset_name)
            
        if status:
            query += " AND status = ?"
            params.append(status.value)
            
        query += " ORDER BY created_at DESC"
        
        with self._get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_job(row) for row in rows]
    
    def get_active_jobs(self) -> List[DocumentationJob]:
        """Get all non-terminal jobs."""
        with self._get_connection() as conn:
            rows = conn.execute("""
                SELECT * FROM documentation_jobs 
                WHERE status IN (?, ?)
                ORDER BY created_at DESC
            """, (JobStatus.CREATED.value, JobStatus.RUNNING.value)).fetchall()
            
            return [self._row_to_job(row) for row in rows]
    
    def record_file_processed(self, job_id: str, filepath: str, 
                            success: bool, error_message: Optional[str] = None,
                            huey_task_id: Optional[str] = None,
                            commit_hash: Optional[str] = None):
        """Record that a file has been processed for a job."""
        with self._get_connection() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO job_processed_files 
                (job_id, filepath, processed_at, success, error_message, huey_task_id, commit_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                job_id,
                filepath,
                datetime.now(timezone.utc).isoformat(),
                success,
                error_message,
                huey_task_id,
                commit_hash
            ))
            
            # Atomically update job counters in a single statement
            conn.execute("""
                UPDATE documentation_jobs
                SET
                    processed_files = processed_files + CASE WHEN ? THEN 1 ELSE 0 END,
                    failed_files = failed_files + CASE WHEN ? THEN 0 ELSE 1 END
                WHERE job_id = ?
            """, (success, success, job_id))
                
            conn.commit()
    
    def get_processed_files_for_job(self, job_id: str) -> List[str]:
        """Get list of successfully processed files for a specific job."""
        with self._get_connection() as conn:
            rows = conn.execute("""
                SELECT filepath FROM job_processed_files 
                WHERE job_id = ? AND success = 1
            """, (job_id,)).fetchall()
            
            return [row['filepath'] for row in rows]
    
    def get_processed_file_details_for_job(self, job_id: str) -> Dict[str, str]:
        """Get successfully processed files with their commit hashes."""
        with self._get_connection() as conn:
            rows = conn.execute("""
                SELECT filepath, commit_hash FROM job_processed_files 
                WHERE job_id = ? AND success = 1
            """, (job_id,)).fetchall()
            
            return {row['filepath']: row['commit_hash'] for row in rows}
    
    def cancel_job(self, job_id: str) -> bool:
        """Cancel a running job, preserving completed work."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE documentation_jobs 
                SET status = ?, completed_at = ?, error_message = ?
                WHERE job_id = ? AND status IN (?, ?)
            """, (
                JobStatus.CANCELLED.value,
                datetime.now(timezone.utc).isoformat(),
                "Job cancelled by user",
                job_id,
                JobStatus.CREATED.value,
                JobStatus.RUNNING.value
            ))
            conn.commit()
            return cursor.rowcount > 0
    
    def cleanup_old_jobs(self, days: int = 30) -> int:
        """Remove completed jobs older than specified days."""
        cutoff = datetime.now(timezone.utc).timestamp() - (days * 24 * 60 * 60)
        
        with self._get_connection() as conn:
            # First delete processed files
            conn.execute("""
                DELETE FROM job_processed_files 
                WHERE job_id IN (
                    SELECT job_id FROM documentation_jobs 
                    WHERE status IN (?, ?, ?)
                    AND datetime(completed_at) < datetime(?, 'unixepoch')
                )
            """, (
                JobStatus.COMPLETED.value,
                JobStatus.FAILED.value, 
                JobStatus.CANCELLED.value,
                cutoff
            ))
            
            # Then delete jobs
            cursor = conn.cursor()
            cursor.execute("""
                DELETE FROM documentation_jobs 
                WHERE status IN (?, ?, ?)
                AND datetime(completed_at) < datetime(?, 'unixepoch')
            """, (
                JobStatus.COMPLETED.value,
                JobStatus.FAILED.value,
                JobStatus.CANCELLED.value,
                cutoff
            ))
            
            conn.commit()
            return cursor.rowcount
    
    def _row_to_job(self, row: sqlite3.Row) -> DocumentationJob:
        """Convert database row to DocumentationJob."""
        data = dict(row)
        
        # Parse JSON fields
        if data.get('file_filters'):
            data['file_filters'] = json.loads(data['file_filters'])
        if data.get('options'):
            data['options'] = json.loads(data['options'])
            
        return DocumentationJob.from_dict(data)