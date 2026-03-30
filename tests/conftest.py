import pytest

pytest_plugins = ["pytester"]


@pytest.fixture
def test_env(pytester, request):
    """
    Common test environment for pytest plugin integration tests.
    It creates a sandbox with the testtrain_pytest plugin and mocks the Testtrain API.
    """
    # 1. Locate the actual plugin in the workspace
    root_dir = request.config.rootpath
    plugin_path = root_dir / "testtrain_pytest.py"
    plugin_content = plugin_path.read_text()

    # 2. Create the plugin file in the sandbox with a unique name to avoid module shadowing
    pytester.makepyfile(testtrain_sandbox=plugin_content)

    # 3. Setup mock and configuration in a conftest.py within the sandbox
    pytester.makeconftest("""
        import pytest
        import requests
        from unittest.mock import MagicMock

        def mock_post(url, json=None, **kwargs):
            payload = json
            import json as json_mod
            with open("api_calls.json", "a") as f:
                f.write(json_mod.dumps(payload) + "\\n")
            m = MagicMock()
            m.ok = True
            m.status_code = 200
            m.json.return_value = {"status": "ok"}
            return m
        
        requests.post = mock_post
    """)
    return pytester
