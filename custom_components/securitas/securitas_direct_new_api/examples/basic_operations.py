"""Basic example for securitas_direct_new_api."""

import asyncio
import logging
from uuid import uuid4

import aiohttp
from securitas_direct_new_api import (
    _LOGGER,
    SecuritasClient,
    HttpTransport,
    ApiDomains,
    SecuritasDirectError,
    generate_device_id,
    generate_uuid,
)


async def do_stuff(client):
    """Exercise some API functions."""
    installations = await client.list_installations()
    print("*** Installations ***\n", installations)

    for installation in installations:
        general_status = await client.get_general_status(installation)
        print("*** General status ***\n", general_status)

        status = await client.check_alarm(installation)
        print("*** Alarm status ***\n", status)

        services = await client.get_services(installation)
        print("*** Services ***\n", services)


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
        transport = HttpTransport(
            session=aiohttp_session,
            base_url=ApiDomains().get_url(country),
        )
        client = SecuritasClient(
            transport=transport,
            country=country,
            language=ApiDomains.language(country),
            username=user,
            password=password,
            device_id=device_id,
            uuid=uuid,
            id_device_indigitall=id_device_indigitall,
        )

        try:
            await client.login()
            print("*** Login ***", client.authentication_token)

            while True:
                await do_stuff(client)
                await asyncio.sleep(60)

        except SecuritasDirectError as err:
            print(f"Error: {err.args}")


if __name__ == "__main__":
    asyncio.run(main())
