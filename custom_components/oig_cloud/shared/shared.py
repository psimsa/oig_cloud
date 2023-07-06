from opentelemetry.sdk.resources import Resource


from ..release_const import COMPONENT_VERSION, SERVICE_NAME

def get_resource(email_hash:str, hass_id: str) -> Resource:

    resource = Resource.create(
        {
            "service.name": SERVICE_NAME,
            "service.version": COMPONENT_VERSION,
            "service.namespace": "oig_cloud",
            "service.instance.id": hass_id,
            "service.instance.user": email_hash,
        }
    )

    return resource