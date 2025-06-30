"""Configuration for FTS5 tokenizer and code-aware searching."""

import re

# Characters configured in tokenizer (from PR 1)
TOKENIZER_CHARS = '._$@->:#'

# Common code operators and patterns
CODE_OPERATORS = {
    '->',   # Object member access (C/C++)
    '::',   # Scope resolution (C++)
    '=>',   # Arrow function (JS)
    '.',    # Property access
    '_',    # Snake case
    '$',    # jQuery, PHP variables
    '@',    # Decorators, directives
    '#',    # CSS IDs, preprocessor
}

# Patterns that indicate code search
CODE_PATTERNS = [
    r'^[_$]',                    # Starts with _ or $
    r'[a-z]+_[a-z]+',           # snake_case
    r'[a-z]+[A-Z]',             # camelCase
    r'::\w+',                   # ::method
    r'->\w+',                   # ->property
    r'\w+\$',                   # observable$
    r'#\w+',                    # #identifier
]

def is_code_pattern(term: str) -> bool:
    """Check if a term looks like a code pattern."""
    # Contains tokenizer special chars
    if any(char in term for char in TOKENIZER_CHARS):
        return True
    
    # Matches code patterns
    for pattern in CODE_PATTERNS:
        if re.search(pattern, term):
            return True
    
    return False