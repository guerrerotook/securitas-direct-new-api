"""Installation/services domain: list installations and fetch service catalog."""

from __future__ import annotations

import logging
from datetime import datetime

import jwt

from ..exceptions import VerisureOwaError
from ..graphql_queries import INSTALLATION_LIST_QUERY, SERVICES_QUERY
from ..models import Attribute, Installation, Service
from ..responses import InstallationListEnvelope
from ._base import _ClientBase

_LOGGER = logging.getLogger(__name__)


class _InstallationMixin(_ClientBase):
    """List installations + fetch services + populate the capabilities cache."""

    async def list_installations(self) -> list[Installation]:
        """List all Verisure OWA installations.

        Returns:
            A list of Installation instances.
        """
        content = {
            "operationName": "mkInstallationList",
            "query": INSTALLATION_LIST_QUERY,
        }
        envelope = await self._execute_graphql(
            content,
            "mkInstallationList",
            InstallationListEnvelope,
        )
        return list(envelope.data.xSInstallations.installations)

    async def get_services(self, installation: Installation) -> list[Service]:
        """Fetch services for an installation.

        Calls xSSrv, extracts the capabilities JWT token and stores it in
        ``self._capabilities[installation.number]``, extracts alarm partitions,
        and builds the Service list.

        Args:
            installation: The installation to query.

        Returns:
            A list of Service instances.
        """
        content = {
            "operationName": "Srv",
            "variables": {"numinst": installation.number, "uuid": self.uuid},
            "query": SERVICES_QUERY,
        }
        await self._check_authentication_token()
        self._register_installation(installation)
        response = await self._execute_raw(content, "Srv", installation=installation)

        installation_data = (response.get("data") or {}).get("xSSrv") or {}
        installation_data = installation_data.get("installation")
        if installation_data is None:
            _LOGGER.warning(
                "API returned no installation data for %s", installation.number
            )
            return []

        config_repo = installation_data.get("configRepoUser") or {}
        installation.alarm_partitions = config_repo.get("alarmPartitions") or []

        raw_data = installation_data.get("services")
        if raw_data is None:
            _LOGGER.warning("API returned no services for %s", installation.number)
            return []

        capabilities = installation_data.get("capabilities")
        if capabilities is None:
            _LOGGER.warning("API returned no capabilities for %s", installation.number)
            return []

        # Decode capabilities JWT and store in self._capabilities. As with
        # the auth token, tokens come from a trusted HTTPS endpoint and are
        # signed with EdDSA, so we don't verify signatures here.
        try:
            token = jwt.decode(capabilities, options={"verify_signature": False})
        except jwt.exceptions.DecodeError as err:
            raise VerisureOwaError("Failed to decode capabilities token") from err

        expiry = datetime.min
        if "exp" in token:
            expiry = datetime.fromtimestamp(token["exp"])

        # Find the installation entry whose 'ins' field matches the requested
        # installation number.  Multi-installation accounts receive a JWT with
        # one entry per installation; always pick by 'ins', not by index.
        cap_set: frozenset[str] = frozenset()
        jwt_installations = token.get("installations") or []
        matched = next(
            (
                entry
                for entry in jwt_installations
                if str(entry.get("ins", "")) == str(installation.number)
            ),
            None,
        )
        if matched is not None:
            cap_set = frozenset(matched.get("cap") or [])
        elif jwt_installations:
            _LOGGER.warning(
                "JWT capabilities token contains no entry for installation %s"
                " (%d other entries present); capability set will be empty",
                installation.number,
                len(jwt_installations),
            )
            _LOGGER.debug(
                "JWT installations[].ins values: %s",
                [entry.get("ins") for entry in jwt_installations],
            )

        self._capabilities[installation.number] = (capabilities, expiry, cap_set)

        # Build service list
        result: list[Service] = []
        for item in raw_data:
            attribute_list: list[Attribute] = []
            attributes = item.get("attributes")
            if attributes and attributes.get("attributes"):
                for attr_item in attributes["attributes"]:
                    attribute_list.append(
                        Attribute(
                            name=attr_item["name"],
                            value=attr_item["value"],
                            active=bool(attr_item["active"]),
                        )
                    )

            result.append(
                Service(
                    id=int(item["idService"]),
                    id_service=int(item["idService"]),
                    active=bool(item["active"]),
                    visible=bool(item["visible"]),
                    bde=bool(item["bde"]),
                    is_premium=bool(item["isPremium"]),
                    cod_oper=bool(item["codOper"]),
                    total_device=int(item.get("totalDevice", 0)),
                    request=item["request"],
                    multiple_req=False,
                    num_devices_mr=0,
                    secret_word=False,
                    min_wrapper_version=item["minWrapperVersion"],
                    description=item.get("description", ""),
                    attributes=attribute_list,
                    listdiy=[],
                    listprompt=[],
                    installation=installation,
                )
            )
        return result
