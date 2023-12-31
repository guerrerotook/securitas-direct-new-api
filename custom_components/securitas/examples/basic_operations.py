"""Basic example for securitas_direct_new_api."""

import asyncio
import sys
from uuid import uuid4

import aiohttp

sys.path.insert(0, "/workspaces/ha-core/config/custom_components/securitas/")

from securitas_direct_new_api.apimanager import (
    ApiManager,
    generate_device_id,
    generate_uuid,
)
from securitas_direct_new_api.exceptions import SecuritasDirectError


async def main():
    """Run Basic Securitas Direct example."""

    user = input("User: ")
    password = input("Password: ")
    country = "es"
    language = "es"
    async with aiohttp.ClientSession() as aiohttp_session:
        uuid = generate_uuid()
        device_id = generate_device_id(language)
        id_device_indigitall = str(uuid4())
        client = ApiManager(
            user,
            password,
            country,
            language,
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

                status = await client.check_alarm_status(installation, reference_id)
                print("*** Alarm status ***\n", status)

                services = await client.get_all_services(installation)
                print("*** Services ***\n", services)

                # for service in services:
                #     sentinel_data = await client.get_sentinel_data(
                #         installation, service
                #     )

        except SecuritasDirectError as err:
            print(f"Error: {err.args}")


if __name__ == "__main__":
    asyncio.run(main())
