"""
Testtrain Pytest Plugin — Real-time test result reporting.

Sends each test result to the Testtrain platform API immediately
after the test finishes, enabling real-time visibility.

Required environment variables (can be set in .env):
  TESTTRAIN_URL   — Platform base URL (e.g. http://localhost:3000)
  TESTTRAIN_RUN_ID      — ID of an existing testrun
  TESTTRAIN_AUTH_TOKEN — Bearer auth token
"""

import os
from datetime import datetime, timezone

import pytest
import requests
from dotenv import load_dotenv

load_dotenv()

TESTTRAIN_URL = os.getenv("TESTTRAIN_URL", "https://testtrain.io")
TESTTRAIN_RUN_ID = os.getenv("TESTTRAIN_RUN_ID")
TESTTRAIN_AUTH_TOKEN = os.getenv("TESTTRAIN_AUTH_TOKEN")

# Only print full test metadata if DEBUG_METADATA=true
DEBUG_METADATA = os.getenv("DEBUG_METADATA", "false").lower() == "true"

import allure_commons

# Stores per-test start timestamps keyed by nodeid
_test_start_times: dict[str, str] = {}


def _utc_now_iso() -> str:
    """Return current UTC time as ISO string with Z suffix."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

# Map pytest outcomes to API states
_STATE_MAP = {
    "passed": "passed",
    "failed": "failed",
    "skipped": "skipped",
}


def _get_allure_title() -> str | None:
    """
    Attempts to extract the Allure title safely.
    Returns the title string if 'everything is ok', otherwise returns None.
    """
    try:
        import allure_commons
        listener = next(
            (p for p in allure_commons.plugin_manager.get_plugins() 
             if type(p).__name__ == "AllureListener"), 
            None
        )
        if not listener:
            return None
            
        test_result = listener.allure_logger.get_test(None)
        if not test_result or not test_result.name:
            return None
            
        return str(test_result.name)
    except Exception:
        return None


def _validate_config():
    """Ensure required env vars are set before the session starts."""
    missing = []
    if not TESTTRAIN_RUN_ID:
        missing.append("TESTTRAIN_RUN_ID")
    if not TESTTRAIN_AUTH_TOKEN:
        missing.append("TESTTRAIN_AUTH_TOKEN")
    if missing:
        pytest.exit(
            f"Testtrain plugin: missing required env vars: {', '.join(missing)}",
            returncode=1,
        )


def pytest_sessionstart(session):
    """Validate configuration at the start of the test session."""
    _validate_config()
    print(f"\n🚀 Testtrain: reporting to {TESTTRAIN_URL}")
    print(f"   Testrun ID: {TESTTRAIN_RUN_ID}\n")


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item):
    """Record the start time before each test runs."""
    _test_start_times[item.nodeid] = _utc_now_iso()


# Stores per-test metadata temporarily to pass from makereport to logreport
_test_meta_stash: dict[str, dict] = {}


def pytest_runtest_makereport(item, call):
    """Capture item markers and allure labels before the report is fully generated."""
    if call.when == "call":
        markers = []
        for mark in item.iter_markers():
            markers.append({
                "name": mark.name,
                "args": [str(a) for a in mark.args],
                "kwargs": {k: str(v) for k, v in mark.kwargs.items()}
            })
            
        # Extract defects from allure_link markers with link_type='issue'
        allure_links = []
        for mark in markers:
            if mark["name"] == "allure_link" and mark["kwargs"].get("link_type") == "issue":
                url = mark["args"][0] if mark["args"] else ""
                name = mark["kwargs"].get("name")
                
                if not url:
                    continue
                    
                issue = {"url": url}
                if name:
                    issue["name"] = name
                allure_links.append(issue)

        # Pull true runtime labels directly from Allure's lifecycle listener
        allure_labels = []
        try:
            listener = next(
                (p for p in allure_commons.plugin_manager.get_plugins() 
                 if type(p).__name__ == "AllureListener"), 
                None
            )
            if listener:
                test_result = listener.allure_logger.get_test(None)
                if test_result:
                    if test_result.labels:
                        allure_labels.extend([{"name": l.name, "value": l.value} for l in test_result.labels])
        except Exception as e:
            if DEBUG_METADATA:
                print(f"Error extracting allure metadata: {e}")

        _test_meta_stash[item.nodeid] = {
            "markers": markers,
            "allure_labels": allure_labels,
            "allure_links": allure_links,
        }


def pytest_runtest_logreport(report):
    """Send test result to the platform API after the 'call' phase."""
    # Regular test results come in the "call" phase.
    # Skipped tests (via skipIf/skip) report in the "setup" phase.
    if report.when == "call" or (report.when == "setup" and report.skipped):
        pass  # Continue to report
    else:
        return

    finished_at = _utc_now_iso()
    started_at = _test_start_times.pop(report.nodeid, finished_at)

    state = _STATE_MAP.get(report.outcome, "failed")

    # Capture output / traceback for failed tests
    output = None
    if report.failed and report.longreprtext:
        output = report.longreprtext
    elif report.skipped and hasattr(report, "wasxfail"):
        output = f"xfail: {report.wasxfail}"

    meta = _test_meta_stash.pop(report.nodeid, {})
    
    # Robust name extraction:
    # 1. Try explicit user properties first (most reliable for custom titles)
    # 2. Try the Allure lifecycle listener
    # 3. Fallback to the full nodeid (no cuts)
    
    allure_title = None
    for key, value in report.user_properties:
        if key == "allure_title":
            allure_title = value
            break
            
    if not allure_title:
        allure_title = _get_allure_title()

    # Use Allure title only if everything is OK (exists, not empty, no errors)
    computed_name = allure_title if allure_title else report.nodeid
    
    if DEBUG_METADATA:
        print(f"\n[Metadata] {report.nodeid}:")
        print(f"  - Computed Name: {computed_name}")
        print(f"  - Markers: {meta.get('markers')}")

    test_entry = {
        "testrunId": TESTTRAIN_RUN_ID,
        "name": computed_name,
        "nodeId": report.nodeid,
        "state": state,
        "startedAt": started_at,
        "finishedAt": finished_at,
    }
    
    defects = meta.get("allure_links")
    if defects:
        test_entry["defects"] = defects

    if output is not None:
        test_entry["output"] = output

    payload = {"tests": [test_entry]}

    try:
        resp = requests.post(
            f"{TESTTRAIN_URL}/api/tests",
            json=payload,
            headers={
                "Authorization": f"Bearer {TESTTRAIN_AUTH_TOKEN}",
                "Content-Type": "application/json",
            },
            timeout=10,
        )
        if resp.ok:
            print(f"  ✅ Reported to TestTrain")
        else:
            print(
                f"  ❌ Failed to report to TestTrain: "
                f"{resp.status_code} {resp.text}"
            )
    except requests.RequestException as exc:
        print(f"  ⚠️  Network error reporting to TestTrain: {exc}")
