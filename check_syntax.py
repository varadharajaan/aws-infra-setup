#!/usr/bin/env python3
"""
Check Python files for syntax errors
"""

import ast
import sys
from pathlib import Path
from text_symbols import Symbols

def check_syntax(file_path):
    """Check if a Python file has syntax errors"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            code = f.read()
        ast.parse(code)
        return True, None
    except SyntaxError as e:
        return False, f"Line {e.lineno}: {e.msg}"
    except Exception as e:
        return False, str(e)

def main():
    root = Path(__file__).parent
    skip_dirs = {'.conda', '.venv', '__pycache__', '.git'}
    skip_files = {'check_syntax.py'}
    
    errors = []
    checked = 0
    
    for py_file in root.rglob('*.py'):
        if py_file.name in skip_files:
            continue
        if any(skip_dir in py_file.parts for skip_dir in skip_dirs):
            continue
        
        checked += 1
        valid, error = check_syntax(py_file)
        if not valid:
            rel_path = py_file.relative_to(root)
            errors.append((rel_path, error))
            print(f"[ERROR] {rel_path}: {error}")
    
    print(f"\n[STATS] Checked: {checked} files")
    print(f"[STATS] Errors: {len(errors)} files")
    
    if errors:
        print("\n[ERROR] Files with syntax errors:")
        for path, error in errors:
            print(f"  - {path}: {error}")
        sys.exit(1)
    else:
        print("[OK] All files have valid syntax!")

if __name__ == "__main__":
    main()
