"""Basic example for securitas_direct_new_api."""

import asyncio
import logging
from uuid import uuid4

import aiohttp
from securitas_direct_new_api import (
    _LOGGER,
    ApiManager,
    SecuritasDirectError,
    generate_device_id,
    generate_uuid,
)


async def do_stuff(client):
    """Exercise some API functions."""
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


async def main():
    """Run Basic Securitas Direct example."""

    _LOGGER.setLevel(10)
    _LOGGER.addHandler(logging.StreamHandler())

    user = input("User: ")
    password = input("Password: ")
    country = "ES"
    async with aiohttp.ClientSession() as aiohttp_session:
        uuid = generate_uuid()
        device_id = generate_device_id(country)
        id_device_indigitall = str(uuid4())
        client = ApiManager(
            user,
            password,
            country,
            aiohttp_session,
            device_id,
            uuid,
            id_device_indigitall,
            2,
        )

        try:
            await client.login()
            print("*** Login ***", client.authentication_token)

            # token = await client.refresh_token()
            # print("Refresh token ***\n", token)
            # return

            while True:
                await do_stuff(client)
                await asyncio.sleep(60)

        except SecuritasDirectError as err:
            print(f"Error: {err.args}")


if __name__ == "__main__":
    asyncio.run(main())
