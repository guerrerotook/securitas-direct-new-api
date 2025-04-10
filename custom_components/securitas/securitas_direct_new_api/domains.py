"""ApiDomain dictionary."""


class ApiDomains:
    """Define the domain list for each country."""

    def __init__(self) -> None:
        """Define default constructor."""
        self.domains = {
            "default": "https://customers.securitasdirect.{country}/owa-api/graphql",
            "AR": "https://customers.verisure.com.ar/owa-api/graphql",
            "BR": "https://customers.verisure.com.br/owa-api/graphql",
            "CL": "https://customers.verisure.cl/owa-api/graphql",
            "ES": "https://customers.securitasdirect.es/owa-api/graphql",
            "FR": "https://customers.securitasdirect.fr/owa-api/graphql",
            "GB": "https://customers.verisure.co.uk/owa-api/graphql",
            "IE": "https://customers.verisure.ie/owa-api/graphql",
            "IT": "https://customers.verisure.it/owa-api/graphql",
            "AR": "https://customers.verisure.com.ar/owa-api/graphql",
        }

        self.languages = {
            "default": "en",
            "BR": "br",  # I know they speak Portuguese, but past code basically did lang=country.lower()
            "CL": "es",
            "ES": "es",
            "FR": "fr",
            "GB": "en",
            "IE": "en",
            "IT": "it",
            "AR": "ar",
        }

    def get_url(self, country: str) -> str:
        """Get the API url for the specified country."""
        country = country.upper()
        result: str = self.domains["default"].format(country=country)
        if country in self.domains:
            result = self.domains[country]
        return result

    def get_language(self, country: str) -> str:
        """Return the language for the specified country."""
        country = country.upper()
        result: str = self.languages["default"]
        if country in self.languages:
            result = self.languages[country]
        return result
