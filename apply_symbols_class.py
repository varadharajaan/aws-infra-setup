#!/usr/bin/env python3
"""
Apply Symbols Class References

This script updates all Python files to:
1. Import the Symbols class from text_symbols
2. Replace hardcoded text symbols with Symbols.* references

Author: varadharajaan
Created: 2025-12-14
"""

import os
import re
from pathlib import Path
from text_symbols import Symbols


# Text symbol mappings to Symbols class attributes
SYMBOL_REPLACEMENTS = {
    r'\[OK\]': 'Symbols.OK',
    r'\[ERROR\]': 'Symbols.ERROR',
    r'\[WARN\]': 'Symbols.WARN',
    r'\[INFO\]': 'Symbols.INFO',
    r'\[START\]': 'Symbols.START',
    r'\[STOP\]': 'Symbols.STOP',
    r'\[PAUSE\]': 'Symbols.PAUSE',
    r'\[SKIP\]': 'Symbols.SKIP',
    r'\[DELETE\]': 'Symbols.DELETE',
    r'\[CLEANUP\]': 'Symbols.CLEANUP',
    r'\[SCAN\]': 'Symbols.SCAN',
    r'\[INSTANCE\]': 'Symbols.INSTANCE',
    r'\[CLUSTER\]': 'Symbols.CLUSTER',
    r'\[REGION\]': 'Symbols.REGION',
    r'\[BANK\]': 'Symbols.ACCOUNT',
    r'\[FOLDER\]': 'Symbols.FOLDER',
    r'\[KEY\]': 'Symbols.KEY',
    r'\[LIST\]': 'Symbols.LIST',
    r'\[STATS\]': 'Symbols.STATS',
    r'\[TIMER\]': 'Symbols.TIMER',
    r'\[TARGET\]': 'Symbols.TARGET',
    r'\[COST\]': 'Symbols.COST',
    r'\[LOG\]': 'Symbols.LOG',
    r'\[DATE\]': 'Symbols.DATE',
    r'\[ALERT\]': 'Symbols.ALERT',
    r'\[TIP\]': 'Symbols.TIP',
    r'\[PROTECTED\]': 'Symbols.PROTECTED',
    r'\[SECURE\]': 'Symbols.SECURE',
    r'\[HEALTH\]': 'Symbols.HEALTH',
    r'\[CHECK\]': 'Symbols.CHECK',
    r'\[X\]': 'Symbols.CROSS',
}

def add_symbols_import(content: str) -> str:
    """Add Symbols import if not present"""
    
    # Check if already imported
    if 'from text_symbols import Symbols' in content:
        return content
    
    # Find the last import statement
    lines = content.split('\n')
    last_import_idx = -1
    
    for idx, line in enumerate(lines):
        if line.strip().startswith(('import ', 'from ')) and not line.strip().startswith('#'):
            last_import_idx = idx
    
    # Insert after last import
    if last_import_idx >= 0:
        lines.insert(last_import_idx + 1, 'from text_symbols import Symbols')
        return '\n'.join(lines)
    
    return content

def replace_text_symbols_in_strings(content: str) -> tuple[str, int]:
    """Replace hardcoded text symbols with Symbols.* references in f-strings and strings"""
    replacements = 0
    
    # Pattern to match f-strings and regular strings
    # We need to be careful to only replace within string literals
    for pattern, replacement in SYMBOL_REPLACEMENTS.items():
        # Find all occurrences in strings (both f"..." and "..." formats)
        # This regex looks for the pattern within quotes
        regex = rf'(["\'])([^"\']*){pattern}([^"\']*)\1'
        
        def replace_in_string(match):
            nonlocal replacements
            quote = match.group(1)
            before = match.group(2)
            after = match.group(3)
            
            # Check if this is an f-string by looking at the character before the quote
            # If we find 'f"' or "f'", we need to use {Symbols.X}
            replacements += 1
            return f'{quote}{before}{{{replacement}}}{after}{quote}'
        
        content = re.sub(regex, replace_in_string, content)
    
    return content, replacements

def process_file(file_path: Path) -> tuple[bool, int]:
    """Process a single Python file"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        original_content = content
        
        # Add import
        content = add_symbols_import(content)
        
        # Replace text symbols
        content, replacements = replace_text_symbols_in_strings(content)
        
        # Only write if changes were made
        if content != original_content:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            return True, replacements
        
        return False, 0
    
    except Exception as e:
        print(f"[ERROR] Failed to process {file_path}: {e}")
        return False, 0

def main():
    """Main execution"""
    print(f"{Symbols.START} Applying Symbols class references across project...")
    
    # Get all Python files
    root_dir = Path(__file__).parent
    python_files = list(root_dir.glob('**/*.py'))
    
    # Skip certain files
    skip_files = {'text_symbols.py', 'apply_text_symbols.py', 'apply_symbols_class.py'}
    
    total_files = 0
    total_replacements = 0
    
    for py_file in python_files:
        if py_file.name in skip_files:
            continue
        
        modified, replacements = process_file(py_file)
        if modified:
            total_files += 1
            total_replacements += replacements
            print(f"{Symbols.OK} {py_file.name}: {replacements} replacements")
    
    print(f"\n{Symbols.OK} Completed!")
    print(f"{Symbols.STATS} Fixed {total_files} files with {total_replacements} total replacements")

if __name__ == "__main__":
    # Import Symbols for use in this script
    main()
