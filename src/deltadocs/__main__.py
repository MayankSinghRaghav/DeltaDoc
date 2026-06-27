"""Module entry so `python -m deltadocs` runs the Apify Actor (see Dockerfile CMD)."""

import asyncio

from .main import main

asyncio.run(main())
