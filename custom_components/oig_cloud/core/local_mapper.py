"""Local/proxy entity mapping for OIG Cloud integration."""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

SUPPORTED_DOMAINS: Tuple[str, ...] = ("sensor", "binary_sensor", "switch")


@dataclass
class ProxyEntityDescriptor:
    """Descriptor for a proxy entity ID."""

    domain: str
    table: str
    key: str
    device_id: str
    is_control: bool
    raw_suffix: str


def normalize_proxy_entity_id(
    entity_id: str, box_id: str
) -> Optional[ProxyEntityDescriptor]:
    """Parse a local proxy entity ID and return a descriptor.

    Args:
        entity_id: Full entity ID like "sensor.oig_local_1234567890_tbl_box_prm2_app"
        box_id: Expected device/box ID

    Returns:
        ProxyEntityDescriptor if valid, None if not matched.
    """
    parts = entity_id.split(".", 1)
    if len(parts) != 2:
        return None
    domain = parts[0]
    rest = parts[1]

    prefix = f"oig_local_{box_id}_"
    if not rest.startswith(prefix):
        return None

    raw_suffix = rest[len(prefix):]
    is_control = raw_suffix.endswith("_cfg")
    if is_control:
        raw_suffix = raw_suffix[:-4]

    table_parts = raw_suffix.rsplit("_", 1)
    if len(table_parts) != 2:
        return None
    table = table_parts[0]  # already has tbl_ prefix, e.g. "tbl_box_prm2"
    key = table_parts[1]

    return ProxyEntityDescriptor(
        domain=domain,
        table=table,
        key=key,
        device_id=box_id,
        is_control=is_control,
        raw_suffix=raw_suffix if not is_control else f"{raw_suffix}_cfg",
    )


@dataclass
class _SuffixUpdate:
    """A single node update for a suffix."""

    node_id: str
    node_key: str


@dataclass
class _SuffixConfig:
    """Configuration for a suffix."""

    table: str
    updates: List[_SuffixUpdate]


_SUFFIX_UPDATES: Dict[str, _SuffixConfig] = {
    "tbl_box_prm2_app": _SuffixConfig(
        table="tbl_box_prm2",
        updates=[_SuffixUpdate(node_id="box_prm2", node_key="app")],
    ),
    "tbl_box_prm2": _SuffixConfig(
        table="tbl_box_prm2",
        updates=[_SuffixUpdate(node_id="box_prm2", node_key="app")],
    ),
}


class LocalUpdateApplier:
    """Applies local entity state changes to an internal payload."""

    def __init__(self, box_id: str) -> None:
        self._box_id = box_id

    def apply_state(
        self, payload: Dict[str, Any], entity_id: str, value: Any, *_: Any
    ) -> bool:
        """Apply state from a local entity to the payload.

        Args:
            payload: Internal data payload keyed by box_id.
            entity_id: Entity ID of the local entity.
            value: New state value.

        Returns:
            True if the value was applied, False if no matching suffix.
        """
        descriptor = normalize_proxy_entity_id(entity_id, self._box_id)
        if descriptor is None:
            return False

        cfg = _SUFFIX_UPDATES.get(descriptor.table)
        if cfg is None:
            return False

        if descriptor.is_control:
            return False

        for update in cfg.updates:
            if descriptor.key == update.node_key:
                box_payload = payload.get(self._box_id, {})
                node_data = box_payload.setdefault(update.node_id, {})
                new_val = int(value) if isinstance(value, (int, float, str)) and str(value).replace(".", "", 1).isdigit() else value
                if node_data.get(update.node_key) == new_val:
                    return False
                node_data[update.node_key] = new_val
                if self._box_id not in payload:
                    payload[self._box_id] = box_payload
                return True

        return False