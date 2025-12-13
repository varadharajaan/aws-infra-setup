#!/usr/bin/env python3
"""
Fix all syntax errors caused by symbol replacement script
"""

import re
from pathlib import Path

def fix_bom(file_path):
    """Remove UTF-8 BOM (U+FEFF) from start of file"""
    try:
        with open(file_path, 'r', encoding='utf-8-sig') as f:
            content = f.read()
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return True, "Removed BOM"
    except Exception as e:
        return False, f"Error: {e}"

def fix_unterminated_fstring(file_path):
    """Fix unterminated f-strings caused by {Symbols.X} replacements"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        original = content
        
        # Fix pattern: f"text {Symbols.X}" (missing closing quote)
        # Look for f" or f' with {Symbols.X} but no closing quote on same line
        lines = content.split('\n')
        fixed_lines = []
        
        for i, line in enumerate(lines):
            # Check if line has unterminated f-string with Symbols
            if re.search(r'[fF]["\'].*\{Symbols\.\w+\}', line):
                # Count quotes
                double_quotes = line.count('"') - line.count('\\"')
                single_quotes = line.count("'") - line.count("\\'")
                
                # If odd number of quotes, likely unterminated
                if line.strip().startswith(('f"', 'f\'', 'F"', 'F\'')):
                    quote = line.strip()[1]
                    if (quote == '"' and double_quotes % 2 == 1) or \
                       (quote == "'" and single_quotes % 2 == 1):
                        # Add closing quote at end if not present
                        if not line.rstrip().endswith(('"', "'")):
                            line = line.rstrip() + quote
            
            fixed_lines.append(line)
        
        content = '\n'.join(fixed_lines)
        
        if content != original:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            return True, "Fixed f-strings"
        return False, "No changes"
    except Exception as e:
        return False, f"Error: {e}"

def fix_unexpected_indent(file_path):
    """Fix unexpected indentation issues"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        original = ''.join(lines)
        fixed = False
        
        # Look for orphaned "from text_symbols import Symbols" with wrong indent
        for i, line in enumerate(lines):
            if 'from text_symbols import Symbols' in line:
                # Check if it's oddly indented (not at start, not proper indent)
                if line.startswith('from text_symbols import Symbols'):
                    # Orphaned import at wrong level - remove it
                    if i > 0 and not lines[i-1].strip().endswith(':'):
                        lines[i] = ''
                        fixed = True
        
        content = ''.join(lines)
        
        if fixed and content != original:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            return True, "Fixed indentation"
        return False, "No changes"
    except Exception as e:
        return False, f"Error: {e}"

def main():
    print("[START] Fixing syntax errors...")
    
    root = Path(__file__).parent
    skip_dirs = {'.conda', '.venv', '__pycache__', '.git'}
    skip_files = {'fix_all_syntax_errors.py', 'text_symbols.py'}
    
    # Files with BOM issues
    bom_files = [
        'asg_cleanup_files.py',
        'eks_cluster_automation.py',
        'iam_cleanup_files.py',
        'launch_template_manager.py',
        'live_health_cost_lookup.py',
        'nuclear_deleteall_ec2.py',
        'ultra_cleanup/ultra_cleanup_asg.py',
        'ultra_cleanup/ultra_cleanup_ebs.py',
        'ultra_cleanup/ultra_cleanup_eks.py',
        'ultra_cleanup/ultra_cleanup_iam.py'
    ]
    
    # Files with f-string issues
    fstring_files = [
        'create_ec2_with_aws_configure.py',
        'ec2_instance_manager.py',
        'lambda_asg_scaling_template.py',
        'lambda_eks_scaling_template.py',
        'smart_spot_selector.py'
    ]
    
    # Files with indent issues
    indent_files = [
        'autoscale_tester.py',
        'auto_scaling_group_manager.py',
        'aws_cloudnuke_manager.py',
        'aws_credential_diagnostics.py',
        'aws_vpc_recovery_tool.py',
        'complete_autoscaler_deployment.py',
        'configure_existing_eks_auth.py',
        'continue_cluster_setup.py',
        'create_ec2_instances.py',
        'custom_cloudwatch_agent_deployer.py',
        'delete_all_aws.py',
        'ec2_ssh_connector.py',
        'eks_cluster_manager.py',
        'enhanced_aws_credential_manager.py',
        'lambda_node_protection_template.py',
        'test_ultra_cleanup_vpc.py',
        'ultra_cleanup/demo_ultra_cleanup_vpc.py'
    ]
    
    fixed_count = 0
    
    # Fix BOM issues
    for file_name in bom_files:
        file_path = root / file_name
        if file_path.exists():
            success, msg = fix_bom(file_path)
            if success:
                fixed_count += 1
                print(f"[OK] {file_name}: {msg}")
    
    # Fix f-string issues
    for file_name in fstring_files:
        file_path = root / file_name
        if file_path.exists():
            success, msg = fix_unterminated_fstring(file_path)
            if success:
                fixed_count += 1
                print(f"[OK] {file_name}: {msg}")
    
    # Fix indentation issues
    for file_name in indent_files:
        file_path = root / file_name
        if file_path.exists():
            success, msg = fix_unexpected_indent(file_path)
            if success:
                fixed_count += 1
                print(f"[OK] {file_name}: {msg}")
    
    print(f"\n[OK] Fixed {fixed_count} files")

if __name__ == "__main__":
    main()
