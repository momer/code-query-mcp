# Code Query MCP Server

A Model Context Protocol (MCP) server that provides intelligent code search across large codebases. Document your code once, then search through it efficiently without loading everything into context.

## Quick Start

### Option 1: Stdio Transport (Recommended)
Single-threaded, managed by Claude automatically:

1. **Install the MCP server:**
   ```bash
   claude mcp add -s user code-query -- python /path/to/code-query-mcp/run_server.py
   ```

2. **Restart Claude**

### Option 2: HTTP Transport (Advanced)
Multi-threaded, supports concurrent requests:

1. **Start the server:**
   ```bash
   python /path/to/code-query-mcp/server.py --http 8000
   ```

2. **Add to Claude:**
   ```bash
   claude mcp add -s user --transport http code-query http://127.0.0.1:8000/mcp
   ```

3. **Restart Claude**

### Using the Server

Once installed, setup your project:
```
"Use code-query MCP to recommend setup"
```

This will analyze your project and guide you through the setup process with exactly the commands you need.

Start searching:
```
"Use code-query MCP to search for 'authentication' in my_project"
"Use code-query MCP to get details for login.ts from my_project"
```

## Key Features

- **🔍 Fast Search**: SQLite FTS5 full-text search with relevance ranking and typo correction
- **📁 Document Entire Codebases**: Analyze and index your code automatically
- **🌳 Git Worktree Support**: Separate datasets for different branches
- **⚡ Model Selection**: Choose between Opus, Sonnet, or custom models during setup
- **🔄 Auto-sync**: Git hooks keep documentation up-to-date
- **💾 Persistent**: Data persists between Claude conversations

## Installation

### Prerequisites
- Python 3.11+ and pip
- jq (for git hooks): `brew install jq` / `apt install jq`

### Setup

1. **Copy the server:**
   ```bash
   mkdir -p ~/mcp-servers
   cp -r /path/to/code-query-mcp ~/mcp-servers/
   cd ~/mcp-servers/code-query-mcp
   pip install -r requirements.txt
   ```

2. **Choose your transport and add to Claude:**

   **Stdio Transport (Recommended):**
   ```bash
   claude mcp add -s user code-query "python ~/mcp-servers/code-query-mcp/run_server.py"
   ```

   **HTTP Transport (for concurrent requests):**
   ```bash
   # First, start the server (keep this running)
   python ~/mcp-servers/code-query-mcp/server.py --http 8000
   
   # Then add to Claude (in another terminal)
   claude mcp add -s user --transport http code-query http://127.0.0.1:8000/mcp
   ```

3. **Verify:**
   ```bash
   claude mcp list
   claude "Use the code-query MCP to check its status"
   ```

### Transport Comparison

| Feature | Stdio Transport | HTTP Transport |
|---------|----------------|----------------|
| **Setup** | Simple - Claude manages process | Manual - keep server running |
| **Concurrency** | Single request at a time | Multiple concurrent requests |
| **Use Case** | Personal development | Production/team use |
| **Reliability** | High - managed by Claude | Manual process management |
| **Port Management** | None needed | Requires available port |

## Common Usage Patterns

### 1. Setup New Project
```
"Use code-query MCP to recommend setup"
```
Analyzes your project and provides step-by-step setup instructions.

### 2. Document Your Codebase  
```
"Use code-query MCP to document directory 'src' as 'my-project'"
```
Claude will automatically analyze and index all your code files.

### 3. Search Your Code
```
"Use code-query MCP to search for 'authentication' in my-project"
"Use code-query MCP to get details for login.ts from my-project"
```

### 4. List Available Projects
```
"Use code-query MCP to list all datasets"
```

## Available Tools

| Command | Purpose |
|---------|---------|
| `recommend_setup` | Analyze project and suggest setup steps |
| `document_directory` | Index and analyze entire codebase |
| `search_files` | Search through documented code |
| `get_file` | Get detailed info for specific files |
| `list_datasets` | Show all indexed projects |
| `create_project_config` | Set up project configuration with model selection |
| `install_pre_commit_hook` | Auto-queue changed files for updates |

## Git Integration

### Auto-sync with Pre-commit Hooks
```
"Use code-query MCP to install pre-commit hook for my-project"  
"Use code-query MCP to install post-merge hook"  # For worktrees
```

When you commit changes, files are automatically queued for documentation updates. Run `.code-query/git-doc-update` to process the queue.

### Worktree Support
Each git worktree gets its own dataset (e.g., `my-project-feature-branch`), automatically forked from main on first use.

## Background Queue Processing

Code Query MCP now supports automated background processing of documentation updates, providing:

- **Instant commits** - No waiting for documentation generation
- **Background processing** - Updates happen asynchronously
- **Better performance** - Handle large codebases efficiently
- **Graceful fallback** - Works even if background worker isn't running

### Quick Start

1. **Setup queue processing:**
   ```bash
   python cli.py worker setup
   ```

2. **Start the background worker:**
   ```bash
   python cli.py worker start
   ```

3. **Make commits as usual:**
   ```bash
   git add .
   git commit -m "Your changes"
   # Files are queued for background processing automatically
   ```

### Configuration

Queue processing is configured in `.code-query/config.json`:

```json
{
  "processing": {
    "mode": "auto",              // "auto" or "manual"
    "fallback_to_sync": true,    // Process synchronously if worker not running
    "batch_size": 5,             // Files per batch
    "retry_attempts": 2,         // Retry failed files
    "retry_delay": 60            // Seconds between retries
  }
}
```

### Worker Commands

```bash
python cli.py worker start    # Start background worker
python cli.py worker stop     # Stop background worker
python cli.py worker restart  # Restart worker
python cli.py worker status   # Check worker status
```

### Processing Modes

- **Manual Mode**: Always processes files synchronously during commit
- **Auto Mode**: Uses background worker if running, falls back to sync if configured

## Troubleshooting

### General Issues
**MCP not recognized:** Restart Claude after installation  
**No search results:** Verify dataset name with `list_datasets`  
**Setup issues:** Use `recommend_setup` for guided configuration

### Stdio Transport Issues
**"Command not found":** Ensure Python path is correct in the command  
**"Permission denied":** Make sure `server.py` is executable or use `python server.py`  
**Server won't start:** Check Python dependencies with `pip install -r requirements.txt`

### HTTP Transport Issues
**"Connection refused":** Ensure the server is running with `python server.py --http 8000`  
**"Port already in use":** Use a different port: `python server.py --http 8001`  
**Server stops unexpectedly:** Check server logs for errors, restart with `python server.py --http 8000`  
**CORS errors:** The server is configured for localhost access only - this is expected

### Switching Between Transports
To switch from stdio to HTTP:
```bash
claude mcp remove code-query
python server.py --http 8000  # Start HTTP server
claude mcp add -s user --transport http code-query http://127.0.0.1:8000/mcp
```

To switch from HTTP to stdio:
```bash
claude mcp remove code-query
# Stop the HTTP server (Ctrl+C)
claude mcp add -s user code-query "python ~/mcp-servers/code-query-mcp/server.py"
```

---

*For detailed documentation, troubleshooting, and advanced features, see the full documentation in the repository.*
