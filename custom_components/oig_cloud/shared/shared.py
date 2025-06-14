from enum import StrEnum
from typing import Dict, Any
import logging

_LOGGER = logging.getLogger(__name__)

try:
    from opentelemetry.sdk.resources import Resource

    _has_opentelemetry = True
except ImportError:
    _LOGGER.warning(
        "OpenTelemetry není nainstalován. Pro povolení telemetrie je nutné ručně nainstalovat balíček: pip install opentelemetry-exporter-otlp-proto-grpc==1.31.0"
    )
    _has_opentelemetry = False
    Resource = None  # type: ignore

from ..release_const import COMPONENT_VERSION, SERVICE_NAME


def get_resource(email_hash: str, hass_id: str) -> Any:
    if not _has_opentelemetry or Resource is None:
        _LOGGER.warning("OpenTelemetry není dostupný, vrací se None místo Resource")
        return None

    try:
        resource: Resource = Resource.create(
            {
                "service.name": SERVICE_NAME,
                "service.version": COMPONENT_VERSION,
                "service.namespace": "oig_cloud",
                "service.instance.id": hass_id,
                "service.instance.user": email_hash,
            }
        )
        return resource
    except Exception as e:
        _LOGGER.error(f"Chyba při vytváření OpenTelemetry Resource: {e}", exc_info=True)
        return None


class GridMode(StrEnum):
    OFF = "Vypnuto / Off"
    ON = "Zapnuto / On"
    LIMITED = "S omezením / Limited"
