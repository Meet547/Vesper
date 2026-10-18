import pytest

from backend.app.config import Settings, validate_track2_isolated_demo


def valid_demo_settings(**overrides):
    values = {
        "_env_file": None,
        "app_mode": "cloud",
        "app_host": "127.0.0.1",
        "app_port": 8012,
        "auth_mode": "none",
        "track2_isolated_demo": True,
        "isolated_demo_identity": "track2-isolated-demo",
        "isolated_demo_graph_name": "vesper_track2_synthetic_test",
        "falkordb_url": "redis://127.0.0.1:6389",
        "falkordb_host": "",
        "falkordb_graph_name": "vesper_track2_synthetic_test",
    }
    values.update(overrides)
    return Settings(**values)


def test_track2_demo_requires_exact_loopback_endpoint_and_graph():
    validate_track2_isolated_demo(valid_demo_settings())


@pytest.mark.parametrize("overrides", [
    {"falkordb_url": "redis://cloud.example:6389"},
    {"falkordb_url": "rediss://127.0.0.1:6389"},
    {"falkordb_url": "redis://127.0.0.1:6379"},
    {"falkordb_url": "redis://127.0.0.1:6389@other.example"},
    {"falkordb_host": "cloud.example"},
    {"falkordb_graph_name": "bitcoin_investigator"},
    {"isolated_demo_identity": "   "},
    {"app_host": "0.0.0.0"},
    {"app_mode": "demo"},
])
def test_track2_demo_rejects_non_isolated_or_ambiguous_configuration(overrides):
    with pytest.raises(RuntimeError, match="loopback FalkorDB URL"):
        validate_track2_isolated_demo(valid_demo_settings(**overrides))
