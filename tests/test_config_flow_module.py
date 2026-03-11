from custom_components.oig_cloud import config_flow
from custom_components.oig_cloud.config.steps import ConfigFlow


def test_config_flow_exports():
    assert config_flow.ConfigFlow is ConfigFlow
    assert "ConfigFlow" in config_flow.__all__
