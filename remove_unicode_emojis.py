#!/usr/bin/env python3
"""
Script to remove Unicode emojis from Python files and replace with text markers.
"""

import os
import re
from pathlib import Path
from text_symbols import Symbols

# Emoji to text replacement mapping
EMOJI_REPLACEMENTS = {
    '🔍': f'{Symbols.SCAN}',
    '✅': f'{Symbols.OK}',
    '❌': f'{Symbols.ERROR}',
    '⚠️': f'{Symbols.WARN}',
    '📊': f'{Symbols.STATS}',
    '🗑️': f'{Symbols.DELETE}',
    '🌐': '[NETWORK]',
    '🔓': '[UNLOCKED]',
    '📎': '[ATTACHED]',
    '🛡️': f'{Symbols.PROTECTED}',
    '🏢': '[ACCOUNT]',
    '🚀': f'{Symbols.START}',
    '📋': f'{Symbols.LIST}',
    '💾': f'{Symbols.INSTANCE}',
    '🗄️': f'{Symbols.CLUSTER}',
    '📸': '[SNAPSHOT]',
    '🌍': f'{Symbols.REGION}',
    '📄': '[FILE]',
    '📝': f'{Symbols.LOG}',
    '🎯': f'{Symbols.TARGET}',
    '❤️': f'{Symbols.HEALTH}',
    '⏳': '[WAIT]',
    '🔒': f'{Symbols.SECURE}',
    '📁': f'{Symbols.FOLDER}',
    '🔧': '[CONFIG]',
    '💡': f'{Symbols.TIP}',
    '🚦': '[TRAFFIC]',
    '🌟': '[STAR]',
    '⭐': '[STAR]',
    '🔥': '[FIRE]',
    '💬': '[COMMENT]',
    '🎨': '[STYLE]',
    '📌': '[PIN]',
    '🏦': f'{Symbols.ACCOUNT}',
    '💻': '[COMPUTE]',
    '🌈': '[RAINBOW]',
    '📡': '[SIGNAL]',
    '🔑': f'{Symbols.KEY}',
    '⚙️': '[SETTINGS]',
    '📦': '[PACKAGE]',
    '🏷️': '[TAG]',
    '🧹': f'{Symbols.CLEANUP}',
    '🎭': '[MASK]',
    '🚨': f'{Symbols.ALERT}',
    '⚡': '[FAST]',
    '🎁': '[GIFT]',
    '🔎': '[SEARCH]',
    '📺': '[DISPLAY]',
    '🗂️': '[ORGANIZER]',
    '💰': f'{Symbols.COST}',
    '🌀': '[SPIN]',
    '🔔': '[NOTIFY]',
    '⭕': '[CIRCLE]',
    '➡️': '[ARROW]',
    '⬅️': '[BACK]',
    '⬆️': '[UP]',
    '⬇️': '[DOWN]',
    '🔗': '[LINK]',
    '📩': '[MESSAGE]',
    '🎪': '[EVENT]',
    '🏃': '[RUN]',
    '🎬': '[ACTION]',
    '🎤': '[VOICE]',
    '📱': '[MOBILE]',
    '🖥️': '[DESKTOP]',
    '⚖️': '[BALANCE]',
    '🎓': '[LEARN]',
    '🔐': '[LOCKED]',
    '🆕': '[NEW]',
    '🆗': f'{Symbols.OK}',
    '🆘': '[SOS]',
    '🔕': '[MUTE]',
    '📶': '[SIGNAL]',
    '🔋': '[BATTERY]',
    '🕐': '[TIME]',
    '🕑': '[TIME]',
    '🕒': '[TIME]',
    '⌚': '[WATCH]',
    '⏰': '[ALARM]',
    '⏱️': f'{Symbols.TIMER}',
    '⏲️': '[CLOCK]',
    '🔜': '[SOON]',
    '🔚': '[END]',
    '🔛': '[ON]',
    '🔝': '[TOP]',
    '🔞': '[ADULT]',
    '⏭️': f'{Symbols.SKIP}',
    '⏸️': f'{Symbols.PAUSE}',
    '⏹️': f'{Symbols.STOP}',
    '⏺️': '[RECORD]',
    '📭': '[MAILBOX]',
    '📬': '[MAILBOX]',
    '📫': '[MAILBOX]',
    '📪': '[MAILBOX]',
    '🎫': '[TICKET]',
    '🎟️': '[TICKET]',
    '🏅': '[MEDAL]',
    '🏆': '[TROPHY]',
    '💥': '[BOOM]',
    '🎉': '[PARTY]',
    '🎊': '[CONFETTI]',
    '🚧': '[CONSTRUCT]',
    '🔴': '[RED]',
    '🟢': '[GREEN]',
    '🟡': '[YELLOW]',
    '🟠': '[ORANGE]',
    '🔵': '[BLUE]',
    '🟣': '[PURPLE]',
    '⚫': '[BLACK]',
    '⚪': '[WHITE]',
    '🟤': '[BROWN]',
    '📍': '[LOCATION]',
    '🎮': '[GAME]',
    '🧪': '[TEST]',
    '🔬': '[SCIENCE]',
    '🧬': '[DNA]',
    '🩺': '[MEDICAL]',
    '💉': '[INJECT]',
    '💊': '[PILL]',
    '🌡️': '[TEMP]',
    '🧯': '[EXTINGUISH]',
    '🛠️': '[TOOLS]',
    '🔨': '[HAMMER]',
    '⚒️': '[PICK]',
    '🪓': '[AXE]',
    '🔪': '[KNIFE]',
    '🗡️': '[SWORD]',
    '⚔️': '[CROSSED]',
    '🛡': '[SHIELD]',
    '🏹': '[BOW]',
    '🎣': '[FISHING]',
    '🥇': '[GOLD]',
    '🥈': '[SILVER]',
    '🥉': '[BRONZE]',
    '📐': '[RULER]',
    '📏': '[STRAIGHTEDGE]',
    '📌': '[PUSHPIN]',
    '📍': '[ROUNDPIN]',
    '✂️': '[SCISSORS]',
    '🖇️': '[PAPERCLIP]',
    '📏': '[MEASURE]',
    '📐': '[TRIANGLE]',
    '✏️': '[PENCIL]',
    '✒️': '[PEN]',
    '🖊️': '[BALLPOINT]',
    '🖋️': '[FOUNTAIN]',
    '✍️': '[WRITING]',
    '💼': '[BRIEFCASE]',
    '📂': '[OPENFOLDER]',
    '📃': '[PAGE]',
    '📑': '[BOOKMARK]',
    '🗒️': '[NOTEPAD]',
    '🗓️': '[CALENDAR]',
    '📆': '[DATES]',
    '📅': f'{Symbols.DATE}',
    '🗃️': '[CARDFILE]',
}

def replace_emojis_in_file(file_path):
    """Replace emojis in a single file."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        original_content = content
        replacements_made = 0
        
        # Replace each emoji with its text equivalent
        for emoji, text in EMOJI_REPLACEMENTS.items():
            if emoji in content:
                count = content.count(emoji)
                content = content.replace(emoji, text)
                replacements_made += count
        
        # Only write if changes were made
        if content != original_content:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"{Symbols.OK} {file_path.name}: {replacements_made} emoji(s) replaced")
            return replacements_made
        
        return 0
        
    except Exception as e:
        print(f"{Symbols.ERROR} Failed to process {file_path}: {e}")
        return 0

def main():
    """Main function to process all Python files."""
    workspace_dir = Path(__file__).parent
    total_files = 0
    total_replacements = 0
    
    print("[START] Removing Unicode emojis from Python files...")
    print("="*80)
    
    # Process all Python files
    for py_file in workspace_dir.glob("*.py"):
        if py_file.name == "remove_unicode_emojis.py":
            continue  # Skip this script itself
        
        replacements = replace_emojis_in_file(py_file)
        if replacements > 0:
            total_files += 1
            total_replacements += replacements
    
    print("="*80)
    print(f"{Symbols.STATS} Processed {total_files} files")
    print(f"{Symbols.STATS} Total replacements: {total_replacements}")
    print("[OK] Emoji removal completed!")

if __name__ == "__main__":
    main()
