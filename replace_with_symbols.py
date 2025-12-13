#!/usr/bin/env python3
"""
Replace Hardcoded Text Symbols with Symbols Class References

This script updates all Python files to replace hardcoded text symbols 
like "[OK]", "[ERROR]", etc. with references to the centralized Symbols class.

Author: varadharajaan
Created: 2025-12-14
"""

import os
import re
from pathlib import Path
from text_symbols import Symbols


# Symbol mapping - pattern to Symbols class attribute
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

def replace_in_fstrings(content: str) -> tuple[str, int]:
    """
    Replace text symbols in f-strings and format strings.
    Converts "[OK]" to {Symbols.OK} in f-strings.
    """
    total_replacements = 0
    
    # Pattern to match f-strings: f"..." or f'...'
    # We'll process each f-string and replace symbols within it
    def process_fstring(match):
        nonlocal total_replacements
        prefix = match.group(1)  # f or F
        quote = match.group(2)   # " or '
        fstring_content = match.group(3)  # content between quotes
        
        # Replace each symbol pattern in the f-string content
        modified_content = fstring_content
        for pattern, replacement in SYMBOL_MAP.items():
            # Count replacements
            count = len(re.findall(pattern, modified_content))
            if count > 0:
                total_replacements += count
                # Replace [SYMBOL] with {Symbols.SYMBOL}
                modified_content = re.sub(pattern, f'{{{replacement}}}', modified_content)
        
        return f'{prefix}{quote}{modified_content}{quote}'
    
    # Match f-strings: f"..." or f'...'
    # This regex handles escaped quotes inside strings
    fstring_pattern = r'([fF])(["\'])(.+?)(?<!\\)\2'
    content = re.sub(fstring_pattern, process_fstring, content, flags=re.DOTALL)
    
    return content, total_replacements

def replace_in_regular_strings(content: str) -> tuple[str, int]:
    """
    Replace text symbols in regular strings (non f-strings).
    Converts regular strings like "[OK] Done" to f"{Symbols.OK} Done"
    """
    total_replacements = 0
    
    # Pattern to match regular strings (not f-strings): "..." or '...'
    # but not f"..." or f'...'
    def process_string(match):
        nonlocal total_replacements
        quote = match.group(1)   # " or '
        string_content = match.group(2)  # content between quotes
        
        # Check if this string contains any symbol patterns
        has_symbol = False
        modified_content = string_content
        for pattern, replacement in SYMBOL_MAP.items():
            if re.search(pattern, modified_content):
                has_symbol = True
                # Count replacements
                count = len(re.findall(pattern, modified_content))
                total_replacements += count
                # Replace [SYMBOL] with {Symbols.SYMBOL}
                modified_content = re.sub(pattern, f'{{{replacement}}}', modified_content)
        
        # If we found symbols, convert to f-string
        if has_symbol:
            return f'f{quote}{modified_content}{quote}'
        else:
            # Return unchanged
            return match.group(0)
    
    # Match regular strings (not f-strings): "..." or '...'
    # Negative lookbehind to exclude f"..."
    string_pattern = r'(?<![fF])(["\'])([^"\']+?)\1'
    content = re.sub(string_pattern, process_string, content)
    
    return content, total_replacements

def process_file(file_path: Path) -> tuple[bool, int]:
    """Process a single Python file"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Skip if file doesn't have text_symbols import
        if 'from text_symbols import Symbols' not in content:
            return False, 0
        
        original_content = content
        
        # Replace in f-strings
        content, fstring_replacements = replace_in_fstrings(content)
        
        # Replace in regular strings (and convert to f-strings)
        content, regular_replacements = replace_in_regular_strings(content)
        
        replacements = fstring_replacements + regular_replacements
        
        # Only write if changes were made
        if content != original_content and replacements > 0:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            return True, replacements
        
        return False, 0
    
    except Exception as e:
        print(f"[ERROR] Failed to process {file_path}: {e}")
        return False, 0

def main():
    """Main execution"""
    
    print(f"{Symbols.START} Replacing hardcoded symbols with Symbols class references...")
    
    # Get all Python files
    root_dir = Path(__file__).parent
    python_files = list(root_dir.glob('**/*.py'))
    
    # Skip certain files
    skip_files = {'text_symbols.py', 'apply_text_symbols.py', 'apply_symbols_class.py', 
                  'replace_with_symbols.py'}
    
    total_files = 0
    total_replacements = 0
    
    for py_file in python_files:
        if py_file.name in skip_files:
            continue
        
        modified, replacements = process_file(py_file)
        if modified:
            total_files += 1
            total_replacements += replacements
            rel_path = py_file.relative_to(root_dir)
            print(f"{Symbols.OK} {rel_path}: {replacements} replacements")
    
    print(f"\n{Symbols.OK} Completed!")
    print(f"{Symbols.STATS} Fixed {total_files} files with {total_replacements} total replacements")

if __name__ == "__main__":
    main()
