#!/usr/bin/env python3
"""
Fix indentation errors caused by imports placed inside methods

This script removes incorrectly indented import statements that were
added inside methods instead of at the top of the file.
"""

import re
from pathlib import Path

def fix_file_indentation(file_path: Path) -> tuple[bool, str]:
    """Fix indentation errors in a single file"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        original = content
        
        # Pattern 1: Remove "            import logging\nfrom text_symbols import Symbols\n            "
        content = re.sub(
            r'            import logging\nfrom text_symbols import Symbols\n            ',
            '            ',
            content
        )
        
        # Pattern 2: Remove "            import traceback\nfrom text_symbols import Symbols\n            "
        content = re.sub(
            r'            import traceback\nfrom text_symbols import Symbols\n            ',
            '            ',
            content
        )
        
        # Pattern 3: Remove standalone "            import logging\n" (12 spaces)
        content = re.sub(
            r'(\n)            import logging\n',
            r'\1',
            content
        )
        
        # Pattern 4: Remove standalone "            import traceback\n" (12 spaces)
        content = re.sub(
            r'(\n)            import traceback\n',
            r'\1',
            content
        )
        
        # Pattern 5: Remove orphaned "from text_symbols import Symbols" lines with wrong indentation
        content = re.sub(
            r'\nfrom text_symbols import Symbols\n            ',
            '\n            ',
            content
        )
        
        if content != original:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            return True, "Fixed"
        
        return False, "No changes needed"
    
    except Exception as e:
        return False, f"Error: {e}"

def main():
    print("[START] Fixing indentation errors...")
    
    root = Path(__file__).parent
    skip_files = {'text_symbols.py', 'complete_symbols_update.py', 'fix_indentation_errors.py'}
    skip_dirs = {'.conda', '.venv', '__pycache__', '.git'}
    
    fixed_count = 0
    error_count = 0
    
    for py_file in root.rglob('*.py'):
        # Skip excluded files/dirs
        if py_file.name in skip_files:
            continue
        if any(skip_dir in py_file.parts for skip_dir in skip_dirs):
            continue
        
        modified, status = fix_file_indentation(py_file)
        if modified:
            fixed_count += 1
            rel_path = py_file.relative_to(root)
            print(f"[OK] {rel_path}: {status}")
        elif "Error" in status:
            error_count += 1
            rel_path = py_file.relative_to(root)
            print(f"[ERROR] {rel_path}: {status}")
    
    print(f"\n[OK] Completed!")
    print(f"[STATS] Fixed: {fixed_count} files, Errors: {error_count}")

if __name__ == "__main__":
    main()
