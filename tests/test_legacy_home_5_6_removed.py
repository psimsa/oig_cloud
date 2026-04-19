"""Test that legacy Home 5/6 standalone mode references have been removed."""

import re
from pathlib import Path

import pytest


def get_repo_root() -> Path:
    """Get the repository root directory."""
    return Path(__file__).parent.parent


ALLOWED_PATTERNS = [
    r"home_5",
    r"home_6",
    r"home_5_home_6",
    r"Home 5 a Home 6 nejsou",
    r"LEGACY_HOME_5_6_ALIASES",
]

EXCLUDED_PATHS = [
    "tests/",
    "docs/",
    "CHANGELOG",
    "services/__init__.py",
    "services.yaml",
    "translations/",
    "shield/validation.py",
    "shield/dispatch.py",
    "shield/queue.py",
    "entities/shield_sensor.py",
    "sensors/",
    "entities/data_sensor.py",
    "entities/computed_sensor.py",
    "sensor.py",
    "www_v2/",
    "core/box_mode_composite.py",
]

HOME_5_6_PATTERN = re.compile(
    r"\b(home_5|home_6|Home 5|Home 6|home5|home6|HOME_5|HOME_6)\b",
    re.IGNORECASE,
)


def is_allowed_match(line_content: str) -> bool:
    """Check if a match is in an allowed pattern or context."""
    for pattern in ALLOWED_PATTERNS:
        if re.search(pattern, line_content, re.IGNORECASE):
            return True
    if '"home_5"' in line_content or '"home_6"' in line_content:
        return True
    if "'home_5'" in line_content or "'home_6'" in line_content:
        return True
    return False


def find_legacy_references(source_file: str) -> list[tuple[int, str, str]]:
    """Find legacy Home 5/6 references in a specific source file."""
    repo_root = get_repo_root()
    file_path = repo_root / source_file

    if not file_path.exists():
        return []

    violations = []
    with open(file_path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            matches = HOME_5_6_PATTERN.findall(line)
            for match in matches:
                if not is_allowed_match(line):
                    violations.append((line_num, line.strip(), match))
    return violations


class TestLegacyHome56Removed:
    """Test that legacy Home 5/6 standalone mode references are removed."""

    def test_no_legacy_home_5_6_in_init(self):
        """Assert no legacy Home 5/6 references in __init__.py."""
        violations = find_legacy_references(
            "custom_components/oig_cloud/__init__.py"
        )
        assert not violations, (
            f"Found legacy Home 5/6 in __init__.py: {violations}"
        )

    def test_no_legacy_home_5_6_in_battery_forecast_types(self):
        """Assert no legacy Home 5/6 references in types.py."""
        violations = find_legacy_references(
            "custom_components/oig_cloud/battery_forecast/types.py"
        )
        assert not violations, (
            f"Found legacy Home 5/6 in types.py: {violations}"
        )

    def test_no_legacy_home_5_6_in_battery_state(self):
        """Assert no legacy Home 5/6 references in battery_state.py."""
        violations = find_legacy_references(
            "custom_components/oig_cloud/battery_forecast/data/battery_state.py"
        )
        assert not violations, (
            f"Found legacy Home 5/6 in battery_state.py: {violations}"
        )

    def test_no_legacy_home_5_6_in_history(self):
        """Assert no legacy Home 5/6 references in history.py."""
        violations = find_legacy_references(
            "custom_components/oig_cloud/battery_forecast/data/history.py"
        )
        assert not violations, (
            f"Found legacy Home 5/6 in history.py: {violations}"
        )

    def test_all_box_modes_has_four_entries(self):
        """Assert ALL_BOX_MODES has exactly 4 entries."""
        file_path = get_repo_root() / "custom_components/oig_cloud/__init__.py"
        content = file_path.read_text()

        match = re.search(r'ALL_BOX_MODES\s*=\s*\[(.*?)\]', content, re.DOTALL)
        assert match, "ALL_BOX_MODES not found in __init__.py"

        modes_str = match.group(1)
        modes = [m.strip().strip('"').strip("'") for m in modes_str.split(",")]
        modes = [m for m in modes if m]

        expected_modes = ["Home 1", "Home 2", "Home 3", "Home UPS"]
        assert len(modes) == 4, (
            f"ALL_BOX_MODES should have exactly 4 entries, got {len(modes)}: {modes}"
        )
        assert modes == expected_modes, (
            f"ALL_BOX_MODES should be {expected_modes}, got {modes}"
        )

    def test_types_no_service_mode_home_5_6_constants(self):
        """Assert SERVICE_MODE_HOME_5 and SERVICE_HOME_6 constants are removed."""
        file_path = get_repo_root() / "custom_components/oig_cloud/battery_forecast/types.py"
        content = file_path.read_text()

        assert "SERVICE_MODE_HOME_5" not in content, (
            "SERVICE_MODE_HOME_5 should be removed from types.py"
        )
        assert "SERVICE_MODE_HOME_6" not in content, (
            "SERVICE_MODE_HOME_6 should be removed from types.py"
        )

    def test_battery_state_no_home_5_6_imports(self):
        """Assert battery_state.py doesn't import SERVICE_MODE_HOME_5/6."""
        file_path = get_repo_root() / "custom_components/oig_cloud/battery_forecast/data/battery_state.py"
        content = file_path.read_text()

        assert "SERVICE_MODE_HOME_5" not in content, (
            "SERVICE_MODE_HOME_5 should be removed from battery_state.py imports"
        )
        assert "SERVICE_MODE_HOME_6" not in content, (
            "SERVICE_MODE_HOME_6 should be removed from battery_state.py imports"
        )

    def test_history_no_home_5_6_mode_mappings(self):
        """Assert history.py map_mode_name_to_id doesn't map Home 5/6."""
        file_path = get_repo_root() / "custom_components/oig_cloud/battery_forecast/data/history.py"
        content = file_path.read_text()

        in_mapping_context = False
        lines = content.split("\n")
        for line in lines:
            if "mode_mapping" in line and "=" in line:
                in_mapping_context = True
            if in_mapping_context:
                if "home_5" in line.lower() and "home_grid" not in line.lower():
                    pytest.fail(f'"Home 5" should be removed from mode_mapping in history.py: {line}')
                if "home_6" in line.lower() and "home_grid" not in line.lower():
                    pytest.fail(f'"Home 6" should be removed from mode_mapping in history.py: {line}')
                if "}" in line and in_mapping_context:
                    in_mapping_context = False