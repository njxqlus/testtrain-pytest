import os
from datetime import datetime, timezone

import pytest
import requests

# Map pytest outcomes to API states
_STATE_MAP = {
    "passed": "passed",
    "failed": "failed",
    "skipped": "skipped",
}

def pytest_addoption(parser):
    """Register configuration options and INI settings."""
    group = parser.getgroup("testtrain", "Testtrain reporting")
    
    # Command line options
    group.addoption("--testtrain-url", help="Platform base URL (default: https://testtrain.io)")
    group.addoption("--testtrain-run-id", help="UUID of an existing testrun")
    group.addoption("--testtrain-auth-token", help="Bearer auth token")
    
    # INI settings (allows putting these in pytest.ini or pyproject.toml)
    parser.addini("testtrain_url", help="Platform base URL")
    parser.addini("testtrain_run_id", help="UUID of an existing testrun")
    parser.addini("testtrain_auth_token", help="Bearer auth token")

@pytest.hookimpl(tryfirst=True)
def pytest_configure(config):
    """Initialize configuration."""
    # 1. Extract values with priority: CLI > Config File > Environment Variable > Default
    url = (config.getoption("--testtrain-url") or 
           config.getini("testtrain_url") or 
           os.getenv("TESTTRAIN_URL") or 
           "https://testtrain.io")
    
    run_id = (config.getoption("--testtrain-run-id") or 
              config.getini("testtrain_run_id") or 
              os.getenv("TESTTRAIN_RUN_ID"))
    
    auth_token = (config.getoption("--testtrain-auth-token") or 
                  config.getini("testtrain_auth_token") or 
                  os.getenv("TESTTRAIN_AUTH_TOKEN"))

    # 2. Store on the config object for later hooks to access
    config._testtrain_url = url.rstrip("/")
    config._testtrain_run_id = run_id
    config._testtrain_auth_token = auth_token
    config._testtrain_enabled = bool(run_id and auth_token)
    
    # 3. Storage for test lifecycle tracking
    # Using a dictionary to store state across hooks
    config._test_start_times = {}
    config._test_meta_stash = {}

def pytest_sessionstart(session):
    """Inform user about reporting status at start of session."""
    config = session.config
    
    if config._testtrain_enabled:
        print(f"\n🚀 Testtrain: reporting to {config._testtrain_url}")
        print(f"   Testrun ID: {config._testtrain_run_id}\n")
    else:
        # We don't exit, just skip reporting.
        # This allows the plugin to be installed but inactive.
        missing = []
        if not config._testtrain_run_id: missing.append("TESTTRAIN_RUN_ID")
        if not config._testtrain_auth_token: missing.append("TESTTRAIN_AUTH_TOKEN")
        
        # Only notify if one is set but not the other, or if they tried to set URL
        if len(missing) < 2 or config.getoption("--testtrain-url"):
             print(f"\n⚠️  Testtrain: reporting disabled. Missing: {', '.join(missing)}")

@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item):
    """Record test start time."""
    if item.config._testtrain_enabled:
        item.config._test_start_times[item.nodeid] = _utc_now_iso()

@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_makereport(item, call):
    """
    Capture metadata and attach config to the report object.
    We use a hookwrapper to ensure we have access to the resulting report.
    """
    outcome = yield
    report = outcome.get_result()
    
    # Attach config so logreport can access it
    report.config = item.config
    
    if not item.config._testtrain_enabled:
        return

    if call.when == "call":
        _extract_metadata(item)

def pytest_runtest_logreport(report):
    """Send results to Testtrain after the phase completes."""
    config = report.config
    if not getattr(config, "_testtrain_enabled", False):
        return

    # report.when can be 'setup', 'call', or 'teardown'
    # We report on 'call' (the test body) or if setup failed (which marks the test as failed/skipped)
    if report.when == "call" or (report.when == "setup" and report.skipped):
        pass
    elif report.when == "setup" and report.failed:
        # Test failed during setup (e.g. error in fixture)
        pass
    else:
        return

    finished_at = _utc_now_iso()
    started_at = config._test_start_times.pop(report.nodeid, finished_at)
    state = _STATE_MAP.get(report.outcome, "failed")
    
    # Capture failure output if exists
    output = None
    if report.failed:
        output = report.longreprtext
    
    meta = config._test_meta_stash.pop(report.nodeid, {})
    
    # Title logic: use Allure title if available, otherwise nodeid
    allure_title = _get_allure_title()
    computed_name = allure_title if allure_title else report.nodeid

    test_entry = {
        "testrunId": config._testtrain_run_id,
        "name": computed_name,
        "nodeId": report.nodeid,
        "state": state,
        "startedAt": started_at,
        "finishedAt": finished_at,
        "defects": meta.get("allure_links", []),
        "output": output or ""  # Ensure it's a string, not None
    }

    try:
        resp = requests.post(
            f"{config._testtrain_url}/api/tests",
            json={"tests": [test_entry]},
            headers={
                "Authorization": f"Bearer {config._testtrain_auth_token}",
                "Content-Type": "application/json",
            },
            timeout=10,
        )
        if not resp.ok:
             print(f"\n  ❌ Failed to report to Testtrain: {resp.status_code}")
             try:
                 print(f"     Error: {resp.json().get('message', resp.text)}")
             except:
                 print(f"     Error: {resp.text}")
    except Exception as e:
        print(f"\n  ⚠️  Error reporting to Testtrain: {e}")

def _utc_now_iso() -> str:
    """Return current UTC time in ISO format with Z suffix."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

def _get_allure_title() -> str | None:
    """Attempts to extract the current test's Allure title."""
    try:
        import allure_commons
        listener = next((p for p in allure_commons.plugin_manager.get_plugins() 
                         if type(p).__name__ == "AllureListener"), None)
        if listener:
            test_result = listener.allure_logger.get_test(None)
            if test_result and test_result.name:
                return str(test_result.name)
    except (ImportError, Exception):
        pass
    return None

def _extract_metadata(item):
    """Internal helper to pull Allure and Pytest markers."""
    markers = []
    for m in item.iter_markers():
        # Corrected extraction logic: avoid shadowing and fix args
        markers.append({
            "name": m.name,
            "args": [str(a) for a in m.args]
        })
    
    allure_links = []
    # Specifically extract 'issue' links from Allure if present
    for mark in item.iter_markers(name="allure_link"):
        if mark.kwargs.get("link_type") == "issue":
            issue = {"url": mark.args[0] if mark.args else ""}
            if mark.kwargs.get("name"):
                issue["name"] = mark.kwargs["name"]
            allure_links.append(issue)

    allure_labels = []
    try:
        import allure_commons
        listener = next((p for p in allure_commons.plugin_manager.get_plugins() 
                         if type(p).__name__ == "AllureListener"), None)
        if listener:
            res = listener.allure_logger.get_test(None)
            if res:
                allure_labels = [{"name": l.name, "value": l.value} for l in res.labels]
    except Exception:
        pass

    item.config._test_meta_stash[item.nodeid] = {
        "markers": markers,
        "allure_labels": allure_labels,
        "allure_links": allure_links,
    }
