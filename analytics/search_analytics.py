"""Main search analytics service."""

from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from .analytics_models import *
from .analytics_storage import AnalyticsStorage
from .metrics_collector import MetricsCollector
import hashlib
import re


class SearchAnalytics:
    """Main search analytics service."""
    
    def __init__(self, storage_backend):
        # Use existing storage backend connection info
        db_path = getattr(storage_backend, 'db_path', ':memory:')
        
        self.analytics_storage = AnalyticsStorage(db_path)
        self.metrics_collector = MetricsCollector(self.analytics_storage)
        self.metrics_collector.start()
    
    def log_query(self, 
                  query: str, 
                  dataset: str,
                  results_count: int, 
                  duration_ms: float,
                  normalized_query: Optional[str] = None,
                  fts_query: Optional[str] = None,
                  error: Optional[Exception] = None,
                  fallback_used: bool = False,
                  client_info: Optional[Dict[str, Any]] = None):
        """Log a search query execution."""
        # Determine status
        if error:
            status = QueryStatus.ERROR
            error_message = str(error)
        elif results_count == 0:
            status = QueryStatus.NO_RESULTS
            error_message = None
        elif fallback_used:
            status = QueryStatus.FALLBACK_USED
            error_message = None
        else:
            status = QueryStatus.SUCCESS
            error_message = None
        
        # Normalize query if not provided
        if normalized_query is None:
            normalized_query = self._normalize_query(query)
        
        # Use FTS query or fallback to normalized
        if fts_query is None:
            fts_query = normalized_query
        
        self.metrics_collector.collect_query(
            query_text=query,
            normalized_query=normalized_query,
            fts_query=fts_query,
            dataset=dataset,
            status=status,
            result_count=results_count,
            duration_ms=duration_ms,
            error_message=error_message,
            fallback_attempted=fallback_used,
            client_info=client_info
        )
    
    def get_slow_queries(self, threshold_ms: int = 1000,
                        limit: int = 100,
                        days_back: int = 7) -> List[SlowQuery]:
        """Get queries slower than threshold."""
        since = datetime.now() - timedelta(days=days_back)
        slow_queries = self.analytics_storage.get_slow_queries(
            threshold_ms=threshold_ms,
            limit=limit,
            since=since
        )
        
        # Add suggestions for each slow query
        for query in slow_queries:
            query.suggestions = self._generate_optimization_suggestions(query)
        
        return slow_queries
    
    def get_failed_queries(self, days_back: int = 7) -> List[FailedQuery]:
        """Get queries that consistently fail."""
        since = datetime.now() - timedelta(days=days_back)
        failed_queries = self.analytics_storage.get_failed_queries(since=since)
        
        # Add alternative suggestions
        for query in failed_queries:
            query.suggested_alternatives = self._suggest_alternatives(query)
        
        return failed_queries
    
    def get_popular_terms(self, days: int = 30, limit: int = 50) -> List[SearchTerm]:
        """Get most popular search terms."""
        return self.analytics_storage.get_popular_terms(days=days, limit=limit)
    
    def get_search_insights(self, 
                           dataset: Optional[str] = None,
                           time_period: str = "day") -> SearchInsights:
        """Get aggregated search insights."""
        # Time range based on period
        if time_period == "hour":
            since = datetime.now() - timedelta(hours=1)
        elif time_period == "day":
            since = datetime.now() - timedelta(days=1)
        elif time_period == "week":
            since = datetime.now() - timedelta(weeks=1)
        else:
            since = datetime.now() - timedelta(days=30)
        
        # Get insights data from storage
        insights_data = self.analytics_storage.get_insights_data(since, dataset)
        overview = insights_data.get("overview", {})
        top_queries = insights_data.get("top_queries", [])
        
        return SearchInsights(
            total_queries=overview.get("total_queries", 0),
            unique_queries=overview.get("unique_queries", 0),
            avg_response_time_ms=overview.get("avg_response_time", 0),
            success_rate=overview.get("success_rate", 0),
            fallback_rate=overview.get("fallback_rate", 0),
            no_results_rate=overview.get("no_results_rate", 0),
            top_queries=top_queries,
            top_datasets=[],  # TODO: Implement dataset aggregation
            query_volume_trend=[],  # TODO: Implement time series
            time_period=time_period
        )
    
    def _normalize_query(self, query: str) -> str:
        """Normalize query for grouping."""
        # Convert to lowercase
        normalized = query.lower().strip()
        
        # Remove extra whitespace
        normalized = re.sub(r'\s+', ' ', normalized)
        
        # Sort terms for consistency (unless it has operators)
        # Check for operators as whole words
        has_operators = any(f' {op} ' in f' {normalized} ' for op in ['and', 'or', 'not', 'near'])
        if not has_operators:
            terms = normalized.split()
            normalized = ' '.join(sorted(terms))
        
        return normalized
    
    def _generate_optimization_suggestions(self, slow_query: SlowQuery) -> List[str]:
        """Generate optimization suggestions for slow queries."""
        suggestions = []
        
        # Check query complexity
        term_count = len(slow_query.query_text.split())
        if term_count > 5:
            suggestions.append("Consider using more specific search terms")
        
        # Check for wildcards
        if '*' in slow_query.query_text:
            suggestions.append("Wildcard searches are slower; try exact terms when possible")
        
        # Check result count
        if slow_query.result_count > 1000:
            suggestions.append("Query returns many results; add more specific terms to narrow down")
        
        # Check for common patterns
        if 'OR' in slow_query.query_text and term_count > 10:
            suggestions.append("Complex OR queries are slow; consider breaking into multiple searches")
        
        return suggestions
    
    def _suggest_alternatives(self, failed_query: FailedQuery) -> List[str]:
        """Suggest alternatives for failed queries."""
        alternatives = []
        query = failed_query.query_text
        
        # Suggest removing special characters
        if any(char in query for char in ['(', ')', '[', ']', '{', '}']):
            cleaned = re.sub(r'[()[\]{}]', '', query)
            alternatives.append(cleaned.strip())
        
        # Suggest splitting camelCase
        if re.search(r'[a-z][A-Z]', query):
            split = re.sub(r'(?<!^)(?=[A-Z])', ' ', query)
            alternatives.append(split.lower())
        
        # Suggest removing underscores
        if '_' in query:
            alternatives.append(query.replace('_', ' '))
        
        # Suggest simpler terms
        if len(query.split()) > 3:
            # Take first two and last terms
            terms = query.split()
            alternatives.append(f"{terms[0]} {terms[-1]}")
        
        return alternatives
    
    def update_metrics(self):
        """Update aggregated metrics (call periodically)."""
        self.analytics_storage.update_hourly_metrics()
    
    def cleanup_old_data(self, retention_days: int = 90):
        """Clean up old analytics data."""
        self.analytics_storage.cleanup_old_data(retention_days)
    
    def shutdown(self):
        """Shutdown analytics service."""
        self.metrics_collector.stop()