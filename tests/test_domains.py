"""Tests for ApiDomains URL and language resolution."""

import pytest

from custom_components.securitas.securitas_direct_new_api.domains import ApiDomains


class TestGetUrl:
    """Tests for ApiDomains.get_url()."""

    @pytest.mark.parametrize(
        ("country", "expected_url"),
        [
            ("ES", "https://customers.securitasdirect.es/owa-api/graphql"),
            ("FR", "https://customers.securitasdirect.fr/owa-api/graphql"),
            ("GB", "https://customers.verisure.co.uk/owa-api/graphql"),
            ("IE", "https://customers.verisure.ie/owa-api/graphql"),
            ("IT", "https://customers.verisure.it/owa-api/graphql"),
            ("AR", "https://customers.verisure.com.ar/owa-api/graphql"),
            ("BR", "https://customers.verisure.com.br/owa-api/graphql"),
            ("CL", "https://customers.verisure.cl/owa-api/graphql"),
            ("PT", "https://customers.verisure.pt/owa-api/graphql"),
        ],
    )
    def test_known_country_returns_specific_url(self, country, expected_url):
        domains = ApiDomains()
        assert domains.get_url(country) == expected_url

    def test_unknown_country_returns_default_with_substitution(self):
        domains = ApiDomains()
        result = domains.get_url("DE")
        assert result == "https://customers.securitasdirect.DE/owa-api/graphql"

    def test_unknown_country_substitutes_uppercase(self):
        domains = ApiDomains()
        result = domains.get_url("nl")
        assert result == "https://customers.securitasdirect.NL/owa-api/graphql"

    @pytest.mark.parametrize("country_input", ["es", "Es", "eS"])
    def test_case_insensitive(self, country_input):
        domains = ApiDomains()
        expected = "https://customers.securitasdirect.es/owa-api/graphql"
        assert domains.get_url(country_input) == expected


class TestGetLanguage:
    """Tests for ApiDomains.get_language()."""

    @pytest.mark.parametrize(
        ("country", "expected_lang"),
        [
            ("ES", "es"),
            ("FR", "fr"),
            ("GB", "en"),
            ("IE", "en"),
            ("IT", "it"),
            ("AR", "ar"),
            ("BR", "br"),
            ("CL", "es"),
            ("PT", "pt"),
        ],
    )
    def test_known_country_returns_correct_language(self, country, expected_lang):
        domains = ApiDomains()
        assert domains.get_language(country) == expected_lang

    def test_unknown_country_returns_default_en(self):
        domains = ApiDomains()
        assert domains.get_language("DE") == "en"

    def test_another_unknown_country_returns_default_en(self):
        domains = ApiDomains()
        assert domains.get_language("JP") == "en"

    @pytest.mark.parametrize("country_input", ["fr", "Fr", "fR"])
    def test_case_insensitive(self, country_input):
        domains = ApiDomains()
        assert domains.get_language(country_input) == "fr"
