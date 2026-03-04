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

_PLUGIN_CONFIG = None

@pytest.hookimpl(tryfirst=True)
def pytest_configure(config):
    """Initialize configuration."""
    global _PLUGIN_CONFIG
    _PLUGIN_CONFIG = config
    
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
    # Each worker (or the main session) has its own storage
    config._test_start_times = {}
    config._test_meta_stash = {}

def pytest_sessionstart(session):
    """Inform user about reporting status at start of session."""
    config = session.config
    
    # Only print on the controller, not on workers
    if hasattr(config, "workerinput"):
        return

    if config._testtrain_enabled:
        print(f"\n🚀 Testtrain: reporting to {config._testtrain_url}")
        print(f"   Testrun ID: {config._testtrain_run_id}\n")
    else:
        missing = []
        if not config._testtrain_run_id: missing.append("TESTTRAIN_RUN_ID")
        if not config._testtrain_auth_token: missing.append("TESTTRAIN_AUTH_TOKEN")
        
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
    Capture metadata and attach to the report object for xdist-safe reporting.
    We use a hookwrapper to ensure we have access to the resulting report.
    """
    try:
        outcome = yield
        report = outcome.get_result()
        
        if not getattr(item.config, "_testtrain_enabled", False):
            return

        # Phase-specific metadata capture (only on worker/local)
        if call.when == "call":
            _extract_metadata(item)
        
        # Bundle data for serialization. We use user_properties as it's automatically 
        # handled by pytest-xdist when sending reports from worker to controller.
        data = {
            "start_time": getattr(item.config, "_test_start_times", {}).get(item.nodeid),
            "finished_at": _utc_now_iso(),
            "meta": getattr(item.config, "_test_meta_stash", {}).get(item.nodeid, {}),
            "name": _get_allure_title() or getattr(report, "nodeid", item.nodeid)
        }
        
        if not hasattr(report, "user_properties"):
            report.user_properties = []
        report.user_properties.append(("testtrain_data", data))
    except Exception as e:
        # Avoid crashing pytest session if reporting logic fails
        print(f"\n  ⚠️  Testtrain internal error: {e}")

def pytest_runtest_logreport(report):
    """Send results to Testtrain after the phase completes."""
    config = _PLUGIN_CONFIG
    if not config or not getattr(config, "_testtrain_enabled", False):
        return

    # In xdist, we only want to report from the controller to avoid duplicates.
    # On workers, we skip this hook.
    if hasattr(config, "workerinput"):
        return

    # We report on 'call' (the test body) or if setup failed (which marks the test as failed/skipped)
    if report.when == "call" or (report.when == "setup" and (report.skipped or report.failed)):
        pass
    else:
        return

    # Extract bundled data from user_properties safely
    data = {}
    for prop in getattr(report, "user_properties", []):
        if isinstance(prop, tuple) and len(prop) == 2 and prop[0] == "testtrain_data":
            data = prop[1]
            break
    
    finished_at = data.get("finished_at") or _utc_now_iso()
    started_at = data.get("start_time") or finished_at
    meta = data.get("meta") or {}
    computed_name = data.get("name") or report.nodeid
    state = _STATE_MAP.get(report.outcome, "failed")
    
    # Capture failure output if exists
    output = None
    if report.failed:
        output = report.longreprtext
    
    test_entry = {
        "testrunId": config._testtrain_run_id,
        "name": computed_name,
        "nodeId": report.nodeid,
        "state": state,
        "startedAt": started_at,
        "finishedAt": finished_at,
        "defects": meta.get("allure_links", []),
        "output": output or ""
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
             error_msg = resp.json().get('message', resp.text) if resp.content else resp.text
             pytest.exit(f"\n❌ Testtrain: Failed to send test result (Status {resp.status_code}).\n   Error: {error_msg}\n   Aborting to ensure no results are lost.")
    except Exception as e:
        pytest.exit(f"\n❌ Testtrain: Connection error during reporting: {e}\n   Aborting to ensure no results are lost.")

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
    try:
        markers = []
        for m in item.iter_markers():
            markers.append({
                "name": m.name,
                "args": [str(a) for a in m.args]
            })
        
        allure_links = []
        seen_urls = set()
        for mark in item.iter_markers(name="allure_link"):
            if mark.kwargs.get("link_type") == "issue":
                url = mark.args[0] if mark.args else ""
                if url not in seen_urls:
                    issue = {"url": url}
                    if mark.kwargs.get("name"):
                        issue["name"] = str(mark.kwargs["name"])
                    allure_links.append(issue)
                    seen_urls.add(url)

        for mark in item.iter_markers(name="issue"):
            url = str(mark.args[0]) if mark.args else ""
            if url not in seen_urls:
                issue = {"url": url}
                if mark.kwargs.get("name"):
                    issue["name"] = str(mark.kwargs["name"])
                allure_links.append(issue)
                seen_urls.add(url)

        allure_labels = []
        try:
            import allure_commons
            listener = next((p for p in allure_commons.plugin_manager.get_plugins() 
                             if type(p).__name__ == "AllureListener"), None)
            if listener:
                res = listener.allure_logger.get_test(None)
                if res:
                    allure_labels = [{"name": str(getattr(l, "name", "")), "value": str(getattr(l, "value", ""))} for l in getattr(res, "labels", [])]
        except Exception:
            pass

        if not hasattr(item.config, "_test_meta_stash"):
            item.config._test_meta_stash = {}
        item.config._test_meta_stash[item.nodeid] = {
            "markers": markers,
            "allure_labels": allure_labels,
            "allure_links": allure_links,
        }
    except Exception:
        pass
