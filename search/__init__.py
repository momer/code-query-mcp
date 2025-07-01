"""Search module for code-aware query building and search services."""

from .query_builder import FTS5QueryBuilder
from .query_strategies import (
    QueryStrategy,
    DefaultQueryStrategy,
    CodeAwareQueryStrategy,
    FallbackStrategy
)
from .query_utils import (
    escape_special_chars,
    extract_terms,
    detect_operators,
    normalize_whitespace,
    is_phrase_query
)
from .tokenizer_config import TOKENIZER_CHARS, CODE_OPERATORS
from .query_sanitizer import FTS5QuerySanitizer, SanitizationConfig
from .search_service import (
    SearchService,
    SearchServiceInterface,
    SearchConfig,
    SearchMode
)
from .models import FileMetadata, SearchResult
from .progressive_search import (
    ProgressiveSearchStrategy,
    SearchStrategy,
    create_default_progressive_strategy
)

__all__ = [
    # Query Builder
    'FTS5QueryBuilder',
    
    # Query Strategies
    'QueryStrategy',
    'DefaultQueryStrategy',
    'CodeAwareQueryStrategy',
    'FallbackStrategy',
    
    # Query Utils
    'escape_special_chars',
    'extract_terms',
    'detect_operators',
    'normalize_whitespace',
    'is_phrase_query',
    
    # Tokenizer Config
    'TOKENIZER_CHARS',
    'CODE_OPERATORS',
    
    # Query Sanitizer
    'FTS5QuerySanitizer',
    'SanitizationConfig',
    
    # Search Service
    'SearchService',
    'SearchServiceInterface',
    'SearchConfig',
    'SearchMode',
    
    # Models
    'FileMetadata',
    'SearchResult',
    
    # Progressive Search
    'ProgressiveSearchStrategy',
    'SearchStrategy',
    'create_default_progressive_strategy'
]