#!/usr/bin/env python3
"""
Script to remove Unicode emojis from Python files and replace with text markers.
"""

from pathlib import Path

# Emoji to text replacement mapping
EMOJI_REPLACEMENTS = {
    '🔍': '[SCAN]',
    '✅': '[OK]',
    '❌': '[ERROR]',
    '⚠️': '[WARN]',
    '📊': '[STATS]',
    '🗑️': '[DELETE]',
    '🌐': '[NETWORK]',
    '🔓': '[UNLOCKED]',
    '📎': '[ATTACHED]',
    '🛡️': '[PROTECTED]',
    '🏢': '[ACCOUNT]',
    '🚀': '[START]',
    '📋': '[LIST]',
    '💾': '[INSTANCE]',
    '🗄️': '[CLUSTER]',
    '📸': '[SNAPSHOT]',
    '🌍': '[REGION]',
    '📄': '[FILE]',
    '📝': '[LOG]',
    '🎯': '[TARGET]',
    '❤️': '[HEALTH]',
    '⏳': '[WAIT]',
    '🔒': '[SECURE]',
    '📁': '[FOLDER]',
    '🔧': '[CONFIG]',
    '💡': '[TIP]',
    '🚦': '[TRAFFIC]',
    '🌟': '[STAR]',
    '⭐': '[STAR]',
    '🔥': '[FIRE]',
    '💬': '[COMMENT]',
    '🎨': '[STYLE]',
    '📌': '[PIN]',
    '🏦': '[BANK]',
    '💻': '[COMPUTE]',
    '🌈': '[RAINBOW]',
    '📡': '[SIGNAL]',
    '🔑': '[KEY]',
    '⚙️': '[SETTINGS]',
    '📦': '[PACKAGE]',
    '🏷️': '[TAG]',
    '🧹': '[CLEANUP]',
    '🎭': '[MASK]',
    '🚨': '[ALERT]',
    '⚡': '[FAST]',
    '🎁': '[GIFT]',
    '🔎': '[SEARCH]',
    '📺': '[DISPLAY]',
    '🗂️': '[ORGANIZER]',
    '💰': '[COST]',
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
    '🆗': '[OK]',
    '🆘': '[SOS]',
    '🔕': '[MUTE]',
    '📶': '[SIGNAL]',
    '🔋': '[BATTERY]',
    '🕐': '[TIME]',
    '🕑': '[TIME]',
    '🕒': '[TIME]',
    '⌚': '[WATCH]',
    '⏰': '[ALARM]',
    '⏱️': '[TIMER]',
    '⏲️': '[CLOCK]',
    '🔜': '[SOON]',
    '🔚': '[END]',
    '🔛': '[ON]',
    '🔝': '[TOP]',
    '🔞': '[ADULT]',
    '⏭️': '[SKIP]',
    '⏸️': '[PAUSE]',
    '⏹️': '[STOP]',
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
    '📅': '[DATE]',
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
            print(f"[OK] {file_path.name}: {replacements_made} emoji(s) replaced")
            return replacements_made
        
        return 0
        
    except Exception as e:
        print(f"[ERROR] Failed to process {file_path}: {e}")
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
    print(f"[STATS] Processed {total_files} files")
    print(f"[STATS] Total replacements: {total_replacements}")
    print("[OK] Emoji removal completed!")

if __name__ == "__main__":
    main()
