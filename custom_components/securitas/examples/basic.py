"""Basic example for securitas_direct_new_api."""

import asyncio
import secrets
import sys
from uuid import uuid4

import aiohttp

sys.path.insert(0, "/workspaces/ha-core/config/custom_components/securitas/")

from securitas_direct_new_api.apimanager import ApiManager
from securitas_direct_new_api.exceptions import SecuritasDirectError


def generate_uuid() -> str:
    """Create a device id."""
    return str(uuid4())  # .replace("-", "")[0:16]


def generate_device_id(lang: str) -> str:
    """Create a device identifier for the API."""
    return secrets.token_urlsafe(16) + ":APA91b" + secrets.token_urlsafe(130)[0:134]


async def main():
    """Basic Securitas Direct example."""

    user = input("User: ")
    password = input("Password: ")
    country = "es"
    async with aiohttp.ClientSession() as aiohttp_session:
        uuid = generate_uuid()
        device_id = generate_device_id("es")
        id_device_indigitall = str(uuid4())
        client = ApiManager(
            user,
            password,
            country,
            country,
            aiohttp_session,
            device_id,
            uuid,
            id_device_indigitall,
        )

        try:
            await client.login()

            # token = await client.refresh_token()
            # print("Refresh token ***\n", token)
            # return

            installations = await client.list_installations()
            print("*** Installations ***\n", installations)

            for installation in installations:
                general_status = await client.check_general_status(installation)
                print("*** General status ***\n", general_status)

                reference_id = await client.check_alarm(installation)
                print("*** Reference ID ***\n", reference_id)

                alarm_status = await client.check_alarm_status(
                    installation, reference_id
                )
                print("*** Alarm Status ***\n", alarm_status)

                services = await client.get_all_services(installation)
                print("*** Services ***\n", services)

                for service in services:
                    sentinel_data = await client.get_sentinel_data(
                        installation, service
                    )
                    print("***Sentinel data ***\n", sentinel_data)

                status = await client.check_alarm_status(installation, reference_id)
                print("*** Alarm status ***\n", status)

        except SecuritasDirectError as err:
            print(f"Error: {err.args}")


if __name__ == "__main__":
    asyncio.run(main())
