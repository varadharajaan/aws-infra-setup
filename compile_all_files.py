#!/usr/bin/env python3
"""
Compile all Python files in the repository to check for syntax errors
"""

import py_compile
import sys
from pathlib import Path
from text_symbols import Symbols

def compile_file(file_path):
    """Compile a single Python file"""
    try:
        py_compile.compile(str(file_path), doraise=True)
        return True, None
    except py_compile.PyCompileError as e:
        return False, str(e)
    except Exception as e:
        return False, str(e)

def main():
    root = Path(__file__).parent
    skip_dirs = {'.conda', '.venv', 'venv', '__pycache__', '.git', 'node_modules'}
    skip_files = {'compile_all_files.py'}
    
    errors = []
    success_count = 0
    total = 0
    
    print("[START] Compiling all Python files...\n")
    
    for py_file in root.rglob('*.py'):
        # Skip excluded directories
        if any(skip_dir in py_file.parts for skip_dir in skip_dirs):
            continue
        if py_file.name in skip_files:
            continue
        
        total += 1
        valid, error = compile_file(py_file)
        
        if valid:
            success_count += 1
        else:
            rel_path = py_file.relative_to(root)
            errors.append((rel_path, error))
            print(f"[ERROR] {rel_path}")
            if error:
                # Extract just the relevant error line
                error_lines = error.split('\n')
                for line in error_lines:
                    if line.strip() and not line.startswith('File'):
                        print(f"        {line.strip()}")
            print()
    
    print("\n" + "="*80)
    print(f"[STATS] Total files checked: {total}")
    print(f"[STATS] Successfully compiled: {success_count}")
    print(f"[STATS] Failed to compile: {len(errors)}")
    print("="*80)
    
    if errors:
        print(f"\n[ERROR] {len(errors)} files with compilation errors:")
        for path, _ in errors:
            print(f"  ✗ {path}")
        sys.exit(1)
    else:
        print("\n[OK] All Python files compiled successfully!")
        sys.exit(0)

if __name__ == "__main__":
    main()
