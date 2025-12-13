"""
Text Symbols Manager

Centralized class for all text symbols and icons used throughout the project.
Provides consistent text-based alternatives to emojis for better compatibility.

Author: varadharajaan
Created: 2025-12-14
"""


class Symbols:
    """Text-based symbols for console output"""
    
    # Status indicators
    OK = "[OK]"
    ERROR = "[ERROR]"
    WARN = "[WARN]"
    INFO = "[INFO]"
    
    # Actions
    START = "[START]"
    STOP = "[STOP]"
    PAUSE = "[PAUSE]"
    SKIP = "[SKIP]"
    DELETE = "[DELETE]"
    CLEANUP = "[CLEANUP]"
    SCAN = "[SCAN]"
    
    # Resources
    INSTANCE = "[INSTANCE]"
    CLUSTER = "[CLUSTER]"
    REGION = "[REGION]"
    ACCOUNT = "[BANK]"
    FOLDER = "[FOLDER]"
    KEY = "[KEY]"
    LIST = "[LIST]"
    
    # Data & Stats
    STATS = "[STATS]"
    TIMER = "[TIMER]"
    TARGET = "[TARGET]"
    COST = "[COST]"
    LOG = "[LOG]"
    DATE = "[DATE]"
    
    # Indicators
    ALERT = "[ALERT]"
    TIP = "[TIP]"
    PROTECTED = "[PROTECTED]"
    SECURE = "[SECURE]"
    HEALTH = "[HEALTH]"
    
    # Symbols
    CHECK = "[CHECK]"
    CROSS = "[X]"
    ARROW = "→"
    BACK = "←"
    UP = "↑"
    DOWN = "↓"
    
    # Numbers
    NUMBER = "[#]"
    SELECT = "[SELECT]"
    
    # Special
    ROCKET = "[ROCKET]"
    CROWN = "[CROWN]"
    STAR = "[STAR]"
    DIAMOND = "[DIAMOND]"
    FIRE = "[FIRE]"
    BRAIN = "[BRAIN]"
    CLOUD = "[CLOUD]"
    LIGHTNING = "[LIGHTNING]"
    SHIELD = "[SHIELD]"
    PARTY = "[PARTY]"


# Legacy compatibility - map common emoji characters to text
EMOJI_TO_TEXT = {
    # Status
    '✅': Symbols.OK,
    '❌': Symbols.ERROR,
    '⚠️': Symbols.WARN,
    'ℹ️': Symbols.INFO,
    
    # Actions
    '🚀': Symbols.START,
    '🗑️': Symbols.DELETE,
    '🔍': Symbols.SCAN,
    '🔄': Symbols.SCAN,
    
    # Resources
    '💾': Symbols.INSTANCE,
    '🗄️': Symbols.CLUSTER,
    '🌍': Symbols.REGION,
    '🏦': Symbols.ACCOUNT,
    '📁': Symbols.FOLDER,
    '🔑': Symbols.KEY,
    '📋': Symbols.LIST,
    
    # Data
    '📊': Symbols.STATS,
    '⏱️': Symbols.TIMER,
    '⏰': Symbols.TIMER,
    '🎯': Symbols.TARGET,
    '💰': Symbols.COST,
    '📝': Symbols.LOG,
    '📅': Symbols.DATE,
    '📖': Symbols.LOG,
    
    # Indicators
    '🛡️': Symbols.PROTECTED,
    '🔒': Symbols.SECURE,
    '❤️': Symbols.HEALTH,
    '💡': Symbols.TIP,
    
    # Symbols
    '⭐': Symbols.STAR,
    '👑': Symbols.CROWN,
    '💎': Symbols.DIAMOND,
    '🔥': Symbols.FIRE,
    '🧠': Symbols.BRAIN,
    '☁️': Symbols.CLOUD,
    '⚡': Symbols.LIGHTNING,
    '🎉': Symbols.PARTY,
    
    # Numbers
    '🔢': Symbols.NUMBER,
    
    # Other
    '📦': '[PACKAGE]',
    '🏷️': '[TAG]',
    '📈': '[UP]',
    '📉': '[DOWN]',
    '🏗️': '[BUILD]',
    '➡️': Symbols.ARROW,
    '⬅️': Symbols.BACK,
    '⬆️': Symbols.UP,
    '⬇️': Symbols.DOWN,
}


def replace_emojis_in_text(text: str) -> str:
    """Replace all emojis in text with their text equivalents"""
    for emoji, replacement in EMOJI_TO_TEXT.items():
        text = text.replace(emoji, replacement)
    return text
