"""ApiDomain dictionary."""


class ApiDomains:
    """Define the domain list for each language."""

    def __init__(self):
        """Define default constructor."""
        self.domains = {
            "default": "https://customers.securitasdirect.{language}/owa-api/graphql",
            "it": "https://customers.verisure.it/owa-api/graphql",
            "es": "https://customers.securitasdirect.es/owa-api/graphql",
            "gb": "https://customers.verisure.co.uk/owa-api/graphql",
        }

    def get_url(self, language: str) -> str:
        """Get the API url for the specified language."""
        result: str = self.domains["default"].format(language=language)
        if language in self.domains:
            result = self.domains[language]
        return result
