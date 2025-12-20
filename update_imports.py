#!/usr/bin/env python3
"""
Script to update import statements in ultra_cleanup files after folder reorganization.
"""

from pathlib import Path

def update_imports_in_file(file_path):
    """Update import statements in a single file."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        original_content = content
        
        # Update imports to add parent directory
        replacements = [
            ('from root_iam_credential_manager import', 'import sys\nimport os\nsys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))\nfrom root_iam_credential_manager import'),
            ('from iam_policy_manager import', 'import sys\nimport os\nsys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))\nfrom iam_policy_manager import'),
        ]
        
        # Check if sys.path.append already exists
        if 'sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))' in content:
            return 0
        
        changes = 0
        for old, new in replacements:
            if old in content and 'sys.path.append' not in content:
                content = content.replace(old, new, 1)  # Replace only first occurrence
                changes += 1
                break  # Only add sys.path.append once
        
        # Only write if changes were made
        if content != original_content:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"[OK] {file_path.name}: Updated imports")
            return 1
        
        return 0
        
    except Exception as e:
        print(f"[ERROR] Failed to process {file_path}: {e}")
        return 0

def main():
    """Main function to update all ultra_cleanup files."""
    workspace_dir = Path(__file__).parent
    ultra_cleanup_dir = workspace_dir / "ultra_cleanup"
    
    if not ultra_cleanup_dir.exists():
        print("[ERROR] ultra_cleanup directory not found!")
        return
    
    print("[START] Updating import statements in ultra_cleanup files...")
    print("="*80)
    
    total_updated = 0
    
    # Process all Python files in ultra_cleanup directory
    for py_file in ultra_cleanup_dir.glob("*.py"):
        if py_file.name == "__init__.py":
            continue
        
        updated = update_imports_in_file(py_file)
        total_updated += updated
    
    print("="*80)
    print(f"[STATS] Updated {total_updated} files")
    print("[OK] Import update completed!")

if __name__ == "__main__":
    main()
