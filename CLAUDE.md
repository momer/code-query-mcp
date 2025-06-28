# Code Query MCP Server - Claude Code Project Guide

## Project Overview

The **Code Query MCP Server** is a Model Context Protocol (MCP) server that provides intelligent code search and documentation capabilities across large codebases. It allows you to document code once, then search through it efficiently without loading everything into context.

### Core Value Proposition
- **Document entire codebases** automatically by analyzing code files and storing structured metadata
- **Search through code** using fast SQLite FTS5 full-text search with relevance ranking  
- **Persist documentation** between Claude conversations in a local database
- **Support Git worktrees** with separate datasets for different branches
- **Auto-sync documentation** via Git hooks when files change

## Architecture Overview

### Key Components
1. **MCP Server** (`server.py`) - Main entry point handling MCP protocol communication
2. **HTTP Server** (`http_server.py`) - Alternative HTTP transport for concurrent requests  
3. **Storage Layer** (`storage/sqlite_storage.py`) - SQLite database with FTS5 search capabilities
4. **Git Integration** (`helpers/git_helper.py`) - Git repository and worktree detection
5. **Tool Definitions** (`tools/mcp_tools.py`) - MCP tool schemas and descriptions

### Architecture Strengths
- **Pragmatic Technology Choices**: SQLite with FTS5 provides zero-dependency, portable, powerful search
- **Decoupled Design**: Clear separation between transport, application, persistence, and utility layers
- **Git-Native Philosophy**: Deep integration with Git workflows, especially robust worktree support
- **Evolving Architecture**: Migration from fragile naming conventions to explicit metadata-driven design

### Critical Design Patterns
1. **Explicit Metadata over Convention**: Uses `dataset_type`, `parent_dataset_id`, `source_branch` columns instead of naming conventions
2. **Robust Git Interaction**: Always use `git rev-parse --git-dir` instead of assuming `.git` is a directory
3. **User-Driven Tools over Magic**: Explicit `sync_dataset` tool instead of fully automatic hooks
4. **Safe Schema Evolution**: Built-in migration system with version tracking

## Setup and Installation

### Prerequisites
- Python 3.11+
- jq (for git hooks): `brew install jq` / `apt install jq`
- Claude Code CLI

### Installation Steps

1. **Copy server to standard location:**
   ```bash
   mkdir -p ~/mcp-servers
   cp -r /path/to/code-query-mcp ~/mcp-servers/
   cd ~/mcp-servers/code-query-mcp
   pip install -r requirements.txt
   ```

2. **Add to Claude (choose transport):**

   **Stdio Transport (Recommended for personal use):**
   ```bash
   claude mcp add -s user code-query "python ~/mcp-servers/code-query-mcp/server.py"
   ```

   **HTTP Transport (for concurrency/debugging):**
   ```bash
   # Start server (keep running)
   python ~/mcp-servers/code-query-mcp/server.py --http 8000
   
   # Add to Claude
   claude mcp add -s user --transport http code-query http://127.0.0.1:8000/mcp
   ```

3. **Verify installation:**
   ```bash
   claude mcp list
   claude "Use the code-query MCP to check its status"
   ```

## Project Setup Workflow

### Standard Setup Process
1. **Get recommendations**: `"Use code-query MCP to recommend setup"`
2. **Document codebase**: `"Use code-query MCP to document directory 'src' as 'my-project'"`
3. **Install git hooks**: `"Use code-query MCP to install pre-commit hook for my-project"`

### Database Location
- **Git repos**: `{repo_root}/.mcp_code_query/code_data.db`
- **Non-git**: `{cwd}/.mcp_code_query/code_data.db`

## Key MCP Tools

### Discovery & Setup
- `recommend_setup` - Analyze project and suggest setup steps (non-destructive)
- `get_project_config` - Get current configuration and setup status
- `create_project_config` - Create/update project configuration

### Code Documentation  
- `document_directory` - Index and analyze entire codebase
- `insert_file_documentation` - Add documentation for specific files
- `update_file_documentation` - Update existing file documentation

### Search & Retrieval (Most Important)
- `search` - **PRIMARY TOOL**: Unified metadata + content search with deduplication
- `search_files` - Search metadata only (overviews, function names, exports)
- `search_full_content` - Search actual source code content with match highlighting
- `get_file` - Get complete documentation for specific files

### Data Management
- `list_datasets` - Show all indexed projects (use when dataset names unknown)
- `clear_dataset` - Remove a dataset
- `get_status` - Check database status

### Git Integration
- `fork_dataset` - Copy dataset for worktree branches
- `sync_dataset` - Sync changes between branch datasets (explicit, user-controlled)
- `install_pre_commit_hook` - Auto-queue changed files for documentation updates
- `install_post_merge_hook` - Set up worktree change syncing
- `cleanup_datasets` - Remove orphaned branch datasets

## Development Commands

### Common Operations
```bash
# Start HTTP server for development/debugging
python server.py --http 8000

# Check database contents  
python scripts/check_db.py $HOME/.mcp_code_query/code_data.db

# Diagnose worktree issues
python scripts/diagnose_worktree.py

# Manual dataset operations
python scripts/manual_fork.py source_dataset target_dataset

# Database migration
python scripts/migrate_db.py
```

### Transport Comparison
| Feature | Stdio Transport | HTTP Transport |
|---------|----------------|----------------|
| **Setup** | Simple - Claude manages | Manual - keep server running |
| **Concurrency** | Single request | Multiple concurrent requests |
| **Use Case** | Personal development | Production/debugging |
| **Debugging** | Limited | Full API access via curl/Postman |

## Important Implementation Details

### Git Worktree Support (Key Feature)
- Automatically detects linked worktrees via `git rev-parse --git-common-dir`
- Creates branch-specific datasets (e.g., `project_feature_branch`)
- Uses explicit metadata columns (`dataset_type`, `parent_dataset_id`) not naming conventions
- Syncs documentation changes between branches via explicit `sync_dataset` tool
- Handles dataset cleanup for deleted branches

### Search Capabilities
- **FTS5 Full-Text Search**: Fast, typo-tolerant search with relevance ranking
- **Metadata Search**: Function names, exports, imports, overviews
- **Content Search**: Actual source code with match highlighting
- **Unified Search**: Combines approaches with automatic deduplication

### Database Schema Evolution
- Uses `storage/migrations.py` for safe schema updates
- Records migration versions in `schema_version` table
- Supports backward compatibility across schema changes

## Testing Strategy

### Current State
- No formal test suite exists
- Relies on manual testing and diagnostic scripts
- Review data in `data/` directory (agent review JSON files)

### Recommended Testing Approach
1. **Unit Tests**: Mock `subprocess` calls, use in-memory SQLite
2. **Integration Tests**: Create temporary Git repos for each test
3. **"Worktree Lifecycle" Test**: Core integration test covering full workflow:
   - Setup main project and dataset
   - Create Git worktree and branch
   - Auto-fork dataset for worktree
   - Isolate changes in worktree dataset
   - Merge branch and sync datasets
   - Cleanup orphaned datasets

## Development Workflow Recommendations

### For Claude Code Instances
1. **Always start with**: `"Use code-query MCP to recommend setup"`
2. **Use unified search**: `search` tool is usually the best starting point
3. **Dataset discovery**: Use `list_datasets` when dataset names are unknown
4. **HTTP for debugging**: Use HTTP transport to test tools directly
5. **Leverage diagnostics**: Use `scripts/diagnose_worktree.py` and `scripts/check_db.py` early

### Git Integration Best Practices
- Install hooks early to keep documentation current
- The system handles branch datasets automatically
- Use explicit `sync_dataset` tool after merges
- Regularly run `cleanup_datasets` to remove stale data

### Search Query Tips
- Use technical terms, not conversational queries
- Good: "auth", "login handler", "websocket"  
- Bad: "how to implement authentication"
- FTS5 supports: phrases in quotes, prefix matching with *, boolean operators

## Architecture Concerns to Watch

### Potential Issues
1. **Subprocess Reliance**: Heavy use of `subprocess` for Git operations (consider GitPython migration)
2. **HTTP State Management**: Class-level session dictionary could be problematic in high-concurrency scenarios
3. **Monolithic Storage**: `sqlite_storage.py` handles many responsibilities (consider breaking into DatasetManager, SearchService, ProjectConfigurator)

### Security Considerations
- Command injection protections are in place for Git operations
- Input validation implemented for dataset names and file paths
- Regular security review of subprocess calls required

## Important Files to Understand

### Current Active Code
- `server.py` - Main MCP server (current, active)
- `storage/sqlite_storage.py` - Core database operations
- `tools/mcp_tools.py` - Tool definitions and schemas
- `helpers/git_helper.py` - Git integration utilities

### Legacy/Historical
- `src/server.py` - Old version, ignore
- `SPECIFICATION.md` - Describes much simpler initial version, not current architecture

### Design Documentation
- `docs/worktree-implementation-plan.md` - Excellent architectural evolution documentation
- `full_content_implementation_summary.md` - Implementation details
- `zen_worktree_fix_review.md` - Critical Git handling fixes

## Quick Productivity Commands

```bash
# Check what datasets exist
claude "Use code-query MCP to list all datasets"

# Get project setup status  
claude "Use code-query MCP to get project config"

# Search across codebase
claude "Use code-query MCP to search for 'authentication' in my-project"

# Get detailed file info
claude "Use code-query MCP to get details for login.ts from my-project"

# Clean up old branch datasets
claude "Use code-query MCP to cleanup datasets with dry_run true"
```

## Dependencies

**Core**: `mcp` (Model Context Protocol library)
**Runtime**: Python 3.11+, SQLite with FTS5 support  
**Optional**: jq (for git hooks)

The project is designed to be lightweight with minimal external dependencies, making it easy to deploy and maintain across different environments.