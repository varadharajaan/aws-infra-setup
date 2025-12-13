#!/usr/bin/env python3
"""
Complete Symbols Update - Add import and replace symbols in ALL Python files

This script:
1. Adds "from text_symbols import Symbols" to files that have text symbols
2. Replaces hardcoded symbols with Symbols class references

Author: varadharajaan
Created: 2025-12-14
"""

import os
import re
from pathlib import Path

# Symbol patterns to detect
SYMBOL_PATTERNS = [
    r'\[OK\]', r'\[ERROR\]', r'\[WARN\]', r'\[INFO\]',
    r'\[START\]', r'\[STOP\]', r'\[SCAN\]', r'\[DELETE\]'
]

# Symbol mappings
SYMBOL_MAP = {
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

def has_text_symbols(content: str) -> bool:
    """Check if content has any text symbols"""
    for pattern in SYMBOL_PATTERNS:
        if re.search(pattern, content):
            return True
    return False

def add_symbols_import(content: str) -> str:
    """Add Symbols import if not present and file has symbols"""
    if 'from text_symbols import Symbols' in content:
        return content
    
    if not has_text_symbols(content):
        return content
    
    lines = content.split('\n')
    last_import_idx = -1
    
    # Find last import line
    for idx, line in enumerate(lines):
        if line.strip().startswith(('import ', 'from ')) and not line.strip().startswith('#'):
            last_import_idx = idx
    
    # Insert after last import
    if last_import_idx >= 0:
        lines.insert(last_import_idx + 1, 'from text_symbols import Symbols')
        return '\n'.join(lines)
    
    return content

def replace_in_fstrings(content: str) -> tuple[str, int]:
    """Replace symbols in f-strings"""
    replacements = 0
    
    def process_fstring(match):
        nonlocal replacements
        prefix = match.group(1)
        quote = match.group(2)
        fstring_content = match.group(3)
        
        modified = fstring_content
        for pattern, replacement in SYMBOL_MAP.items():
            count = len(re.findall(pattern, modified))
            if count > 0:
                replacements += count
                modified = re.sub(pattern, f'{{{replacement}}}', modified)
        
        return f'{prefix}{quote}{modified}{quote}'
    
    fstring_pattern = r'([fF])(["\'])(.+?)(?<!\\)\2'
    content = re.sub(fstring_pattern, process_fstring, content, flags=re.DOTALL)
    
    return content, replacements

def replace_in_regular_strings(content: str) -> tuple[str, int]:
    """Replace symbols in regular strings and convert to f-strings"""
    replacements = 0
    
    def process_string(match):
        nonlocal replacements
        quote = match.group(1)
        string_content = match.group(2)
        
        has_symbol = False
        modified = string_content
        for pattern, replacement in SYMBOL_MAP.items():
            if re.search(pattern, modified):
                has_symbol = True
                count = len(re.findall(pattern, modified))
                replacements += count
                modified = re.sub(pattern, f'{{{replacement}}}', modified)
        
        if has_symbol:
            return f'f{quote}{modified}{quote}'
        return match.group(0)
    
    string_pattern = r'(?<![fF])(["\'])([^"\']+?)\1'
    content = re.sub(string_pattern, process_string, content)
    
    return content, replacements

def process_file(file_path: Path) -> tuple[bool, int]:
    """Process a single file"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        original = content
        
        # Add import
        content = add_symbols_import(content)
        
        # Replace in f-strings
        content, f_reps = replace_in_fstrings(content)
        
        # Replace in regular strings
        content, r_reps = replace_in_regular_strings(content)
        
        total_reps = f_reps + r_reps
        
        if content != original and (total_reps > 0 or 'from text_symbols import Symbols' not in original):
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            return True, total_reps
        
        return False, 0
    
    except Exception as e:
        print(f"[ERROR] {file_path.name}: {e}")
        return False, 0

def main():
    print("[START] Processing all Python files...")
    
    root = Path(__file__).parent
    skip_files = {'text_symbols.py', 'apply_text_symbols.py', 'replace_with_symbols.py',  
                  'apply_symbols_class.py', 'complete_symbols_update.py'}
    skip_dirs = {'.conda', '.venv', '__pycache__', '.git'}
    
    total_files = 0
    total_replacements = 0
    
    for py_file in root.rglob('*.py'):
        # Skip excluded files/dirs
        if py_file.name in skip_files:
            continue
        if any(skip_dir in py_file.parts for skip_dir in skip_dirs):
            continue
        
        modified, reps = process_file(py_file)
        if modified:
            total_files += 1
            total_replacements += reps
            rel_path = py_file.relative_to(root)
            if reps > 0:
                print(f"[OK] {rel_path}: {reps} replacements")
    
    print(f"\n[OK] Completed!")
    print(f"[STATS] Updated {total_files} files with {total_replacements} replacements")

if __name__ == "__main__":
    main()
