"""NKZ Water Studio — services package."""

import importlib
import logging

logger = logging.getLogger(__name__)


def get_tile_service():
    """Lazy import tile_service to avoid boto3 dependency at import time."""
    return importlib.import_module(".tile_service", package="app.services")
