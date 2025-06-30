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
    'SanitizationConfig'
]