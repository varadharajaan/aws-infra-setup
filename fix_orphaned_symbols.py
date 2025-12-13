#!/usr/bin/env python3
"""
Remove all orphaned 'from text_symbols import Symbols' lines that cause indentation errors
"""

import re
from pathlib import Path

def fix_orphaned_symbols_import(file_path):
    """Remove orphaned Symbol imports in the middle of code"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        original = content
        
        # Pattern: standalone "from text_symbols import Symbols" that's not at the top
        # and not part of the import block
        lines = content.split('\n')
        fixed_lines = []
        
        for i, line in enumerate(lines):
            # Skip orphaned "from text_symbols import Symbols" lines
            if line.strip() == 'from text_symbols import Symbols':
                # Check if this is in the import section (first 50 lines typically)
                if i < 50:
                    # Check if surrounded by imports
                    prev_is_import = False
                    next_is_import = False
                    
                    if i > 0:
                        prev_line = lines[i-1].strip()
                        prev_is_import = prev_line.startswith(('import ', 'from ')) or prev_line == ''
                    
                    if i < len(lines) - 1:
                        next_line = lines[i+1].strip()
                        next_is_import = next_line.startswith(('import ', 'from ')) or next_line == '' or next_line.startswith('#')
                    
                    # Keep it if it's in proper import section
                    if prev_is_import or next_is_import or i < 30:
                        fixed_lines.append(line)
                    # Otherwise skip it (orphaned in middle of code)
                else:
                    # Definitely orphaned if after line 50
                    continue
            else:
                fixed_lines.append(line)
        
        content = '\n'.join(fixed_lines)
        
        if content != original:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            return True, "Removed orphaned import"
        return False, "No changes"
    except Exception as e:
        return False, f"Error: {e}"

def main():
    print("[START] Removing orphaned Symbol imports...")
    
    root = Path(__file__).parent
    skip_dirs = {'.conda', '.venv', 'venv', '__pycache__', '.git'}
    skip_files = {'fix_orphaned_symbols.py', 'text_symbols.py'}
    
    fixed_count = 0
    
    for py_file in root.rglob('*.py'):
        if py_file.name in skip_files:
            continue
        if any(skip_dir in py_file.parts for skip_dir in skip_dirs):
            continue
        
        modified, status = fix_orphaned_symbols_import(py_file)
        if modified:
            fixed_count += 1
            rel_path = py_file.relative_to(root)
            print(f"[OK] {rel_path}: {status}")
    
    print(f"\n[OK] Fixed {fixed_count} files")

if __name__ == "__main__":
    main()
