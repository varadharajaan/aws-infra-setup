#!/usr/bin/env python3
"""
Remove all orphaned 'from text_symbols import Symbols' lines that cause indentation errors
"""

from pathlib import Path
import re

def fix_orphaned_imports(file_path):
    """Remove orphaned Symbol imports in the middle of code"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        original = ''.join(lines)
        fixed_lines = []
        skip_next = False
        
        for i, line in enumerate(lines):
            # Skip this line if marked
            if skip_next:
                skip_next = False
                continue
                
            # Check if this is an orphaned Symbol import (not at top of file, not after except/import)
            if 'from text_symbols import Symbols' in line and i > 10:
                # Check context - if previous line isn't an import statement, this is orphaned
                if i > 0:
                    prev_line = lines[i-1].strip()
                    # If previous line isn't import/from/except/try, this is orphaned
                    if not (prev_line.startswith(('import ', 'from ', 'except', 'try')) or 
                           prev_line.endswith(':')):
                        # Skip this orphaned line
                        continue
            
            fixed_lines.append(line)
        
        content = ''.join(fixed_lines)
        
        if content != original:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            return True, "Removed orphaned imports"
        return False, "No changes"
    except Exception as e:
        return False, f"Error: {e}"

def main():
    print("[START] Removing orphaned Symbol imports...")
    
    files_to_fix = [
        'asg_cleanup_files.py',
        'create_ec2_instances.py',
        'eks_cluster_automation.py',
        'eks_cluster_manager.py',
        'iam_cleanup_files.py',
        'live_health_cost_lookup.py',
    ]
    
    root = Path(__file__).parent
    fixed = 0
    
    for file_name in files_to_fix:
        file_path = root / file_name
        if file_path.exists():
            success, msg = fix_orphaned_imports(file_path)
            if success:
                fixed += 1
                print(f"[OK] {file_name}: {msg}")
    
    print(f"\n[OK] Fixed {fixed} files")

if __name__ == "__main__":
    main()
