"""Utilities for query processing and manipulation."""

import re
from typing import List, Set

def escape_special_chars(query: str) -> str:
    """Escape special characters for FTS5."""
    # FTS5 special characters that need escaping
    special_chars = '"'
    
    for char in special_chars:
        query = query.replace(char, f'{char}{char}')
    
    return query

def extract_terms(query: str) -> List[str]:
    """Extract individual terms from query."""
    # Handle quoted phrases
    phrases = []
    remaining = query
    
    # Extract quoted phrases first
    quote_pattern = r'"([^"]+)"'
    for match in re.finditer(quote_pattern, query):
        phrases.append(match.group(1))
        remaining = remaining.replace(match.group(0), ' ')
    
    # Split remaining by whitespace
    terms = remaining.split()
    
    # Combine phrases and terms
    all_terms = phrases + [t for t in terms if t]
    
    return all_terms

def detect_operators(query: str) -> Set[str]:
    """Detect FTS5 operators in query."""
    operators = {'AND', 'OR', 'NOT', 'NEAR'}
    found = set()
    
    # Split by whitespace but also check for NEAR( pattern
    if 'NEAR(' in query:
        found.add('NEAR')
    
    tokens = query.split()
    for token in tokens:
        if token in operators:
            found.add(token)
    
    return found

def normalize_whitespace(query: str) -> str:
    """Normalize whitespace in query."""
    return ' '.join(query.split())

def is_phrase_query(query: str) -> bool:
    """Check if entire query is a phrase."""
    query = query.strip()
    return query.startswith('"') and query.endswith('"')

