"""Constants."""


class SentinelName:
    """Define the sentinel string name for each language."""

    def __init__(self) -> None:
        """Define default constructor."""
        self.sentinel_name = {
            "default": "CONFORT",
            "es": "CONFORT",
            "br": "COMFORTO",
            "pt": "COMFORTO",
        }

    def get_sentinel_name(self, language: str) -> str:
        """Get the sentinel string for the language."""
        result: str = self.sentinel_name["default"].format(language=language)
        if language in self.sentinel_name:
            result = self.sentinel_name[language]
        return result
