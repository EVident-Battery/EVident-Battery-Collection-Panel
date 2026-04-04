"""Platform-appropriate font families."""
import sys

if sys.platform == "darwin":
    DEFAULT_FONT_FAMILY = ".AppleSystemUIFont"
    MONO_FONT_FAMILY = "Menlo"
elif sys.platform == "win32":
    DEFAULT_FONT_FAMILY = "Segoe UI"
    MONO_FONT_FAMILY = "Consolas"
else:
    DEFAULT_FONT_FAMILY = "Sans Serif"
    MONO_FONT_FAMILY = "Monospace"
