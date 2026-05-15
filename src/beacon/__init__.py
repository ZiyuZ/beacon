"""Beacon - lightweight personal log dashboard.

Subpackages:

* :mod:`beacon.api`     - FastAPI routes (server)
* :mod:`beacon.cli`     - ``beacon`` command-line entry point (server)
* :mod:`beacon.client`  - HTTP client utilities (BeaconClient, demo CLI)

The package ``__init__`` is intentionally empty so that importing
:mod:`beacon.client` from a script does not transitively load
FastAPI / SQLModel.
"""
