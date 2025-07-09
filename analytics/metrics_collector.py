"""Asynchronous metrics collection with minimal performance impact."""

from typing import Optional, Dict, Any, List
from queue import Queue, Full, Empty
from threading import Thread, Event
from datetime import datetime
import uuid
import time
import logging
from .analytics_models import QueryLogEntry, QueryStatus
from .analytics_storage import AnalyticsStorage

logger = logging.getLogger(__name__)


class MetricsCollector:
    """Collects metrics asynchronously with minimal performance impact."""
    
    def __init__(self, storage: AnalyticsStorage, 
                 batch_size: int = 100,
                 flush_interval: float = 5.0):
        self.storage = storage
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self.queue: Queue[QueryLogEntry] = Queue(maxsize=10000)
        self.shutdown_event = Event()
        self.worker_thread: Optional[Thread] = None
        self.enabled = True
    
    def start(self):
        """Start the background metrics collection thread."""
        if self.worker_thread is None or not self.worker_thread.is_alive():
            self.worker_thread = Thread(target=self._worker, daemon=True)
            self.worker_thread.start()
            logger.info("Metrics collector started")
    
    def stop(self):
        """Stop the metrics collection thread."""
        self.shutdown_event.set()
        if self.worker_thread:
            self.worker_thread.join(timeout=10)
        logger.info("Metrics collector stopped")
    
    def collect_query(self,
                     query_text: str,
                     normalized_query: str,
                     fts_query: str,
                     dataset: str,
                     status: QueryStatus,
                     result_count: int,
                     duration_ms: float,
                     error_message: Optional[str] = None,
                     fallback_attempted: bool = False,
                     client_info: Optional[Dict[str, Any]] = None):
        """Collect a query execution metric."""
        if not self.enabled:
            return
        
        entry = QueryLogEntry(
            query_id=str(uuid.uuid4()),
            query_text=query_text,
            normalized_query=normalized_query,
            fts_query=fts_query,
            dataset=dataset,
            status=status,
            result_count=result_count,
            duration_ms=duration_ms,
            timestamp=datetime.now(),
            error_message=error_message,
            fallback_attempted=fallback_attempted,
            client_info=client_info
        )
        
        try:
            self.queue.put_nowait(entry)
        except Full:
            # Queue full, metrics dropped (acceptable for analytics)
            logger.warning("Metrics queue full, dropping query log entry")
    
    def _worker(self):
        """Background worker to process metrics queue."""
        batch = []
        last_flush = time.time()
        
        while not self.shutdown_event.is_set():
            try:
                # Try to get items from queue with timeout
                timeout = max(0.1, self.flush_interval - (time.time() - last_flush))
                
                try:
                    entry = self.queue.get(timeout=timeout)
                    batch.append(entry)
                except Empty:
                    # Timeout - check if we should flush
                    pass
                
                # Flush if batch is full or interval elapsed
                should_flush = (
                    len(batch) >= self.batch_size or
                    time.time() - last_flush >= self.flush_interval
                )
                
                if should_flush and batch:
                    self._flush_batch(batch)
                    batch = []
                    last_flush = time.time()
                    
            except Exception as e:
                logger.error(f"Error in metrics worker: {e}")
        
        # Final flush on shutdown
        if batch:
            self._flush_batch(batch)
    
    def _flush_batch(self, batch: List[QueryLogEntry]):
        """Flush a batch of metrics to storage."""
        try:
            self.storage.insert_query_logs_batch(batch)
            logger.debug(f"Flushed {len(batch)} query metrics")
        except Exception as e:
            logger.error(f"Failed to flush metrics batch: {e}")