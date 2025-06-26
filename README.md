# Code Query MCP Server

A Model Context Protocol (MCP) server that provides intelligent code search across large codebases. Document your code once, then search through it efficiently without loading everything into context.

## Quick Start

1. **Install the MCP server:**
   ```bash
   claude mcp add code-query -s user -- python ~/mcp-servers/code-query-mcp/run_server.py
   ```

2. **Restart Claude**

3. **Setup your project:**
   ```
   "Use code-query MCP to recommend setup"
   ```
   
   This will analyze your project and guide you through the setup process with exactly the commands you need.

4. **Start searching:**
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

2. **Add to Claude:**
   ```bash
   claude mcp add code-query -s user -- python ~/mcp-servers/code-query-mcp/run_server.py
   ```

3. **Verify:**
   ```bash
   claude mcp list
   claude "Use the code-query MCP to check its status"
   ```

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

## Troubleshooting

**MCP not recognized:** Restart Claude after installation  
**No search results:** Verify dataset name with `list_datasets`  
**Setup issues:** Use `recommend_setup` for guided configuration

---

*For detailed documentation, troubleshooting, and advanced features, see the full documentation in the repository.*
