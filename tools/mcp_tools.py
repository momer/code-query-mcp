"""MCP tool definitions for Code Query MCP Server."""

from typing import List
from mcp.types import Tool


def get_tools() -> List[Tool]:
    """Return all available MCP tools."""
    return [
        Tool(
            name="import_data",
            description="Import JSON files from directory into named dataset",
            inputSchema={
                "type": "object",
                "properties": {
                    "dataset_name": {
                        "type": "string",
                        "description": "Name for this dataset"
                    },
                    "directory": {
                        "type": "string",
                        "description": "Relative directory path containing JSON files"
                    },
                    "replace": {
                        "type": "boolean",
                        "description": "Replace existing dataset if it exists",
                        "default": False
                    }
                },
                "required": ["dataset_name", "directory"]
            }
        ),
        Tool(
            name="recommend_setup",
            description="Check your project setup and get recommendations for Code Query MCP. This tool only analyzes your current state - it does NOT make any changes. It will: 1) Check for existing datasets that match your project, 2) Detect if configuration files exist, 3) Check git hook status, and 4) Recommend next steps. Use this to see what setup is needed without modifying anything.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_name": {
                        "type": "string",
                        "description": "Name for the project (auto-detected if not provided)"
                    },
                    "source_directory": {
                        "type": "string",
                        "description": "Directory to document (auto-detected if not provided)"
                    }
                },
                "required": []
            }
        ),
        Tool(
            name="search_files",
            description="""Search files in dataset by query string. Returns limited overview information (filepath, filename, overview, ddd_context, match_snippet) for discovery. Use mcp__code-query__get_file tool to retrieve complete detailed documentation including functions, exports, imports, types, and constants. Use mcp__code-query__get_project_config first to check for active dataset, then mcp__code-query__list_datasets if dataset name is unknown.

IMPORTANT: This is code search, not web search. Use short, focused queries with technical terms that would appear in code.
Good: "auth", "login handler", "websocket"
Bad: "how to implement authentication" (too conversational)

FTS5 Query Syntax:
• Basic: Multiple words are ANDed together (e.g., "auth login")
• Phrases: Use quotes for exact phrases (e.g., "user authentication")
• Prefix: Add * for prefix matching (e.g., "auth*" matches authentication, authorize)
• Boolean: OR, NOT operators (e.g., "login OR signup", "auth NOT test")
• NEAR: Find terms within proximity (e.g., "NEAR(auth login, 5)")
• Columns: Search specific fields (e.g., "overview:authentication", "{overview filename}:login")
• Initial: Use ^ to match at start (e.g., "^class")

Examples:
- "auth* login" - Files with auth-prefixed words AND login
- '"user authentication" OR "user auth"' - Either exact phrase
- "controller NOT test" - Controllers excluding test files
- "overview:security imports:crypto" - Security in overview AND crypto in imports""",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query"
                    },
                    "dataset_name": {
                        "type": "string",
                        "description": "Dataset to search in. Use mcp__code-query__get_project_config tool first to check for active dataset, then mcp__code-query__list_datasets if unknown."
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum results to return",
                        "default": 10
                    }
                },
                "required": ["query", "dataset_name"]
            }
        ),
        Tool(
            name="search",
            description="""Unified search combining both metadata and full-content search for comprehensive code discovery. Returns results from both search types, with deduplication and clear categorization. This is the recommended search tool for most use cases as it provides complete coverage.

IMPORTANT: This searches both metadata (overviews, function names, exports, imports) AND actual source code content. Perfect for comprehensive discovery when you're not sure whether to use metadata or content search.

Use cases:
- General code exploration and discovery
- Finding files/functions when unsure of exact location
- Comprehensive search across both documentation and implementation
- Getting complete picture of where terms appear in the codebase

Returns structured results with:
- metadata_results: Files found through metadata search (overviews, function names, etc.)
- content_results: Files found only through full-content search  
- search_summary: Statistics about the search results
- Automatic deduplication of files found in both searches""",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query for unified search"
                    },
                    "dataset_name": {
                        "type": "string",
                        "description": "Dataset to search in. Use mcp__code-query__get_project_config first to check for active dataset, then mcp__code-query__list_datasets if unknown."
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum results to return per search type",
                        "default": 10
                    }
                },
                "required": ["query", "dataset_name"]
            }
        ),
        Tool(
            name="search_full_content",
            description="""Search full file contents using FTS5 for comprehensive code search. This provides deep content search within actual source code files, complementing the metadata search provided by search_files. Returns snippets of actual code content where matches are found.

IMPORTANT: This searches the actual source code content, not just metadata. Use for finding specific code patterns, function implementations, variable usage, etc.

Good use cases:
- "function calculateTotal" - Find function definitions
- "const API_URL" - Find constant declarations  
- "import React" - Find import statements
- "catch (error)" - Find error handling patterns
- "SELECT * FROM" - Find SQL queries

Returns content snippets with [MATCH] markers around found terms.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query for full content search"
                    },
                    "dataset_name": {
                        "type": "string",
                        "description": "Dataset to search in. Use mcp__code-query__get_project_config first to check for active dataset, then mcp__code-query__list_datasets if unknown."
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum results to return",
                        "default": 10
                    }
                },
                "required": ["query", "dataset_name"]
            }
        ),
        Tool(
            name="get_file",
            description="Get complete detailed documentation for a specific file including functions, exports, imports, types, interfaces, classes, constants, dependencies, and other comprehensive analysis. This provides full details that mcp__code-query__search_files does not include. Supports partial path matching (e.g., 'login.ts' finds 'src/auth/login.ts'). Use mcp__code-query__get_project_config first to check for active dataset, then mcp__code-query__list_datasets if dataset name is unknown.",
            inputSchema={
                "type": "object",
                "properties": {
                    "filepath": {
                        "type": "string",
                        "description": "Full or partial path to the file. Use % for wildcards."
                    },
                    "dataset_name": {
                        "type": "string",
                        "description": "Dataset containing the file. Use mcp__code-query__get_project_config first to check for active dataset, then mcp__code-query__list_datasets if dataset name is unknown."
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum results for partial matches",
                        "default": 10
                    }
                },
                "required": ["filepath", "dataset_name"]
            }
        ),
        Tool(
            name="list_domains",
            description="List all unique DDD context domains in dataset. Use mcp__code-query__get_project_config first to check for active dataset, then mcp__code-query__list_datasets if dataset name is unknown.",
            inputSchema={
                "type": "object",
                "properties": {
                    "dataset_name": {
                        "type": "string",
                        "description": "Dataset to analyze. Use mcp__code-query__get_project_config first to check for active dataset, then mcp__code-query__list_datasets if dataset name is unknown."
                    }
                },
                "required": ["dataset_name"]
            }
        ),
        Tool(
            name="list_datasets",
            description="List all loaded datasets with their names, sources, and file counts. Use this when you need to discover available dataset names.",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="get_status",
            description="Get current database status",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="clear_dataset",
            description="Clear a specific dataset. Use mcp__code-query__get_project_config first to check for active dataset, then mcp__code-query__list_datasets if dataset name is unknown.",
            inputSchema={
                "type": "object",
                "properties": {
                    "dataset_name": {
                        "type": "string",
                        "description": "Dataset to clear. Use mcp__code-query__get_project_config first to check for active dataset, then mcp__code-query__list_datasets if dataset name is unknown."
                    }
                },
                "required": ["dataset_name"]
            }
        ),
        Tool(
            name="document_directory",
            description="Generate orchestration instructions for documenting a directory of code files",
            inputSchema={
                "type": "object",
                "properties": {
                    "dataset_name": {
                        "type": "string",
                        "description": "Name for this dataset"
                    },
                    "directory": {
                        "type": "string",
                        "description": "Relative directory path to document"
                    },
                    "exclude_patterns": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Patterns to exclude (e.g., '*.test.js', 'temp/*')"
                    },
                    "batch_size": {
                        "type": "integer",
                        "description": "Number of files per agent batch",
                        "default": 20
                    }
                },
                "required": ["dataset_name", "directory"]
            }
        ),
        Tool(
            name="insert_file_documentation",
            description="Insert analyzed file documentation into dataset (used by agents)",
            inputSchema={
                "type": "object",
                "properties": {
                    "dataset_name": {
                        "type": "string",
                        "description": "Dataset to insert into. Use mcp__code-query__get_project_config first to check for active dataset, then mcp__code-query__list_datasets if dataset name is unknown."
                    },
                    "filepath": {
                        "type": "string",
                        "description": "Full file path"
                    },
                    "filename": {
                        "type": "string",
                        "description": "File name"
                    },
                    "overview": {
                        "type": "string",
                        "description": "Brief file overview"
                    },
                    "functions": {
                        "type": "object",
                        "description": "Functions with their details"
                    },
                    "exports": {
                        "type": "object",
                        "description": "Exported items"
                    },
                    "imports": {
                        "type": "object",
                        "description": "Imported items"
                    },
                    "types_interfaces_classes": {
                        "type": "object",
                        "description": "Type definitions"
                    },
                    "constants": {
                        "type": "object",
                        "description": "Constant definitions"
                    },
                    "ddd_context": {
                        "type": "string",
                        "description": "DDD domain context"
                    },
                    "dependencies": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "External dependencies"
                    },
                    "other_notes": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Additional notes"
                    }
                },
                "required": ["dataset_name", "filepath", "filename", "overview"]
            }
        ),
        Tool(
            name="update_file_documentation",
            description="Update existing file documentation in dataset. Only updates provided fields.",
            inputSchema={
                "type": "object",
                "properties": {
                    "dataset_name": {
                        "type": "string",
                        "description": "Dataset containing the file. Use mcp__code-query__get_project_config first to check for active dataset, then mcp__code-query__list_datasets if dataset name is unknown."
                    },
                    "filepath": {
                        "type": "string",
                        "description": "Full file path to update"
                    },
                    "filename": {
                        "type": "string",
                        "description": "Updated file name (optional)"
                    },
                    "overview": {
                        "type": "string",
                        "description": "Updated file overview (optional)"
                    },
                    "functions": {
                        "type": "object",
                        "description": "Updated functions (optional)"
                    },
                    "exports": {
                        "type": "object",
                        "description": "Updated exports (optional)"
                    },
                    "imports": {
                        "type": "object",
                        "description": "Updated imports (optional)"
                    },
                    "types_interfaces_classes": {
                        "type": "object",
                        "description": "Updated type definitions (optional)"
                    },
                    "constants": {
                        "type": "object",
                        "description": "Updated constants (optional)"
                    },
                    "ddd_context": {
                        "type": "string",
                        "description": "Updated DDD context (optional)"
                    },
                    "dependencies": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Updated dependencies (optional)"
                    },
                    "other_notes": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Updated notes (optional)"
                    }
                },
                "required": ["dataset_name", "filepath"]
            }
        ),
        Tool(
            name="get_project_config",
            description="Get comprehensive project configuration including dataset status, git hooks, and setup completeness. This tool helps understand what setup steps have been completed and what remains to be done.",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="install_pre_commit_hook",
            description="Install pre-commit hook for automatic documentation update queuing",
            inputSchema={
                "type": "object",
                "properties": {
                    "dataset_name": {
                        "type": "string",
                        "description": "Dataset name to use for this project"
                    },
                    "mode": {
                        "type": "string",
                        "description": "Hook mode: 'queue' (default) queues files for manual update",
                        "enum": ["queue"],
                        "default": "queue"
                    }
                },
                "required": ["dataset_name"]
            }
        ),
        Tool(
            name="create_project_config",
            description="Create or update code-query project configuration file (.code-query/config.json)",
            inputSchema={
                "type": "object",
                "properties": {
                    "dataset_name": {
                        "type": "string",
                        "description": "Dataset name for this project"
                    },
                    "exclude_patterns": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Patterns to exclude (e.g., '*.test.js', 'node_modules/*'). Defaults to common exclusions if not provided."
                    }
                },
                "required": ["dataset_name"]
            }
        ),
        Tool(
            name="fork_dataset",
            description="Fork (copy) a dataset to a new name. Useful for git worktrees where you want to work on the same codebase with different branches. Use mcp__code-query__get_project_config first to check for active dataset, then mcp__code-query__list_datasets if source dataset name is unknown.",
            inputSchema={
                "type": "object",
                "properties": {
                    "source_dataset": {
                        "type": "string",
                        "description": "Source dataset to copy from. Use mcp__code-query__get_project_config first to check for active dataset, then mcp__code-query__list_datasets if dataset name is unknown."
                    },
                    "target_dataset": {
                        "type": "string",
                        "description": "New dataset name to create"
                    }
                },
                "required": ["source_dataset", "target_dataset"]
            }
        ),
        Tool(
            name="install_post_merge_hook",
            description="Install post-merge hook for syncing worktree changes back to main dataset",
            inputSchema={
                "type": "object",
                "properties": {
                    "main_dataset": {
                        "type": "string",
                        "description": "Main dataset name to sync to (defaults to config datasetName)"
                    }
                },
                "required": []
            }
        ),
        Tool(
            name="sync_dataset",
            description="Syncs documentation changes from a source dataset (e.g., feature branch) to a target dataset (e.g., main). Use after merging branches.",
            inputSchema={
                "type": "object",
                "properties": {
                    "source_dataset": {
                        "type": "string",
                        "description": "The dataset to sync changes from (e.g., 'project__wt_feature_branch')"
                    },
                    "target_dataset": {
                        "type": "string", 
                        "description": "The dataset to sync changes to (e.g., 'project_main')"
                    },
                    "source_ref": {
                        "type": "string",
                        "description": "Git ref (branch/commit) for source dataset"
                    },
                    "target_ref": {
                        "type": "string",
                        "description": "Git ref (branch/commit) for target dataset"
                    }
                },
                "required": ["source_dataset", "target_dataset", "source_ref", "target_ref"]
            }
        ),
        Tool(
            name="cleanup_datasets",
            description="Find and optionally remove orphaned datasets whose git branches no longer exist",
            inputSchema={
                "type": "object",
                "properties": {
                    "dry_run": {
                        "type": "boolean",
                        "description": "If true, only list orphans without deleting. Defaults to true for safety.",
                        "default": True
                    }
                }
            }
        ),
        Tool(
            name="find_files_needing_catchup",
            description="Find files that have changed since they were last documented",
            inputSchema={
                "type": "object",
                "properties": {
                    "dataset_name": {
                        "type": "string",
                        "description": "Dataset to check for files needing catchup. Use get_project_config first to check for active dataset, then list_datasets if dataset name is unknown."
                    }
                },
                "required": ["dataset_name"]
            }
        ),
        Tool(
            name="backport_commit_to_file",
            description="Associate a commit hash with a file that was documented without commit tracking",
            inputSchema={
                "type": "object",
                "properties": {
                    "dataset_name": {
                        "type": "string",
                        "description": "Dataset containing the file. Use get_project_config first to check for active dataset, then list_datasets if dataset name is unknown."
                    },
                    "filepath": {
                        "type": "string",
                        "description": "Full path to the file to update"
                    },
                    "commit_hash": {
                        "type": "string",
                        "description": "Git commit hash to associate with the file"
                    }
                },
                "required": ["dataset_name", "filepath", "commit_hash"]
            }
        ),
        Tool(
            name="bulk_backport_commits",
            description="Backport commit hash to all files in a dataset that don't have commit tracking",
            inputSchema={
                "type": "object",
                "properties": {
                    "dataset_name": {
                        "type": "string",
                        "description": "Dataset to update. Use get_project_config first to check for active dataset, then list_datasets if dataset name is unknown."
                    },
                    "commit_hash": {
                        "type": "string",
                        "description": "Git commit hash to associate with files (optional - uses current HEAD if not provided)"
                    }
                },
                "required": ["dataset_name"]
            }
        )
    ]