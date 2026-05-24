"""Fixture 02: async def with @vera.audit — async-ness is preserved."""

import vera


@vera.audit("fetch_data")
async def fetch_data(url):
    return await _fetch(url)


async def _fetch(url):
    return url
