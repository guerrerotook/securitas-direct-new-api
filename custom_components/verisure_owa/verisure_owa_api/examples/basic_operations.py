"""Basic example for verisure_owa_api."""

import asyncio
import logging
from uuid import uuid4

import aiohttp
from verisure_owa_api import (
    _LOGGER,
    VerisureOwaClient,
    HttpTransport,
    ApiDomains,
    VerisureOwaError,
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
    """Run Basic Verisure OWA example."""

    _LOGGER.setLevel(10)
    _LOGGER.addHandler(logging.StreamHandler())

    user = input("User: ")
    password = input("Password: ")
    country = "ES"
    async with aiohttp.ClientSession() as aiohttp_session:
        uuid = generate_uuid()
        device_id = generate_device_id(country)
        id_device_indigitall = str(uuid4())
        api_domains = ApiDomains()
        transport = HttpTransport(
            session=aiohttp_session,
            base_url=api_domains.get_url(country),
        )
        client = VerisureOwaClient(
            transport=transport,
            country=country,
            language=api_domains.get_language(country),
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

        except VerisureOwaError as err:
            print(f"Error: {err.args}")


if __name__ == "__main__":
    asyncio.run(main())
