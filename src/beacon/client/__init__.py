"""Client-side utilities for talking to a Beacon server.

This subpackage is import-light on purpose so that user scripts that only
need ``remote_sink`` do not pay the cost of pulling in FastAPI, SQLModel,
Jinja2, etc. via the server-side modules.
"""

from beacon.client._client import BeaconClient

__all__ = ["BeaconClient"]
