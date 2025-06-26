#!/usr/bin/env python3
import os
import sys

# Capture the original working directory before changing anything
original_cwd = os.getcwd()

# Add the server directory to Python path for imports without changing working directory
script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, script_dir)

# Set environment variable so the server knows the original client working directory
os.environ['MCP_CLIENT_ROOT'] = original_cwd

# Import and run the server
from server import main
import asyncio

if __name__ == "__main__":
    asyncio.run(main())