"""Apply text symbols throughout the project"""
from text_symbols import EMOJI_TO_TEXT
import pathlib
from text_symbols import Symbols

def main():
    skip_files = {'remove_unicode_emojis.py', 'text_symbols.py', 'apply_text_symbols.py'}
    files = [f for f in pathlib.Path('.').rglob('*.py') if f.name not in skip_files]
    
    count = 0
    total_replacements = 0
    
    for file_path in files:
        try:
            content = file_path.read_text(encoding='utf-8')
            original = content
            file_replacements = 0
            
            for emoji, text in EMOJI_TO_TEXT.items():
                if emoji in content:
                    occurrences = content.count(emoji)
                    content = content.replace(emoji, text)
                    file_replacements += occurrences
            
            if content != original:
                file_path.write_text(content, encoding='utf-8')
                count += 1
                total_replacements += file_replacements
                print(f"Fixed {file_path.name}: {file_replacements} replacements")
        
        except Exception as e:
            print(f"Error processing {file_path}: {e}")
    
    print(f"\nDone! Fixed {count} files with {total_replacements} total replacements")

if __name__ == "__main__":
    main()
