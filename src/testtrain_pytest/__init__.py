import os
import time
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
    group.addoption(
        "--testtrain-url", help="Platform base URL (default: https://testtrain.io)"
    )
    group.addoption("--testtrain-run-id", help="UUID of an existing testrun")
    group.addoption("--testtrain-auth-token", help="Bearer auth token")
    group.addoption(
        "--testtrain-create-tag",
        help="Create tags if they do not exist on the platform (default: true)",
    )

    # INI settings (allows putting these in pytest.ini or pyproject.toml)
    parser.addini("testtrain_url", help="Platform base URL")
    parser.addini("testtrain_run_id", help="UUID of an existing testrun")
    parser.addini("testtrain_auth_token", help="Bearer auth token")
    parser.addini(
        "testtrain_create_tag", help="Create tags if they do not exist on the platform"
    )


_PLUGIN_CONFIG = None


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config):
    """Initialize configuration."""
    global _PLUGIN_CONFIG
    _PLUGIN_CONFIG = config

    # 1. Extract values with priority: CLI > Config File > Environment Variable > Default
    url = (
        config.getoption("--testtrain-url")
        or config.getini("testtrain_url")
        or os.getenv("TESTTRAIN_URL")
        or "https://testtrain.io"
    )

    run_id = (
        config.getoption("--testtrain-run-id")
        or config.getini("testtrain_run_id")
        or os.getenv("TESTTRAIN_RUN_ID")
    )

    auth_token = (
        config.getoption("--testtrain-auth-token")
        or config.getini("testtrain_auth_token")
        or os.getenv("TESTTRAIN_AUTH_TOKEN")
    )

    create_tag = (
        config.getoption("--testtrain-create-tag")
        or config.getini("testtrain_create_tag")
        or os.getenv("TESTTRAIN_CREATE_TAG")
        or "true"
    )

    # 2. Store on the config object for later hooks to access
    config._testtrain_url = url.rstrip("/")
    config._testtrain_run_id = run_id
    config._testtrain_auth_token = auth_token
    config._testtrain_create_tag = str(create_tag).lower() == "true"
    config._testtrain_enabled = bool(run_id and auth_token)

    # 3. Storage for test lifecycle tracking
    config._test_start_times = {}
    config._test_meta_stash = {}
    config._test_outcome_stash = {}


def pytest_sessionstart(session):
    """Inform user about reporting status at start of session."""
    config = session.config

    if hasattr(config, "workerinput"):
        return

    if config._testtrain_enabled:
        print(f"\n🚀 Testtrain: reporting to {config._testtrain_url}")
        print(f"   Testrun ID: {config._testtrain_run_id}\n")
    else:
        missing = []
        if not config._testtrain_run_id:
            missing.append("TESTTRAIN_RUN_ID")
        if not config._testtrain_auth_token:
            missing.append("TESTTRAIN_AUTH_TOKEN")

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
    Capture metadata and outcome across all phases and attach to teardown for reporting.
    """
    try:
        outcome = yield
        report = outcome.get_result()

        if not getattr(item.config, "_testtrain_enabled", False):
            return

        # 1. Capture metadata for the current phase
        _extract_metadata(item)

        # 2. Accumulate overall test state
        if item.nodeid not in item.config._test_outcome_stash:
            item.config._test_outcome_stash[item.nodeid] = {
                "outcome": "passed",
                "longrepr": None,
                "reported": False,
            }

        stash = item.config._test_outcome_stash[item.nodeid]
        if report.failed:
            # Prefer body/setup failures over teardown failures
            if stash["outcome"] != "failed" or report.when != "teardown":
                stash["outcome"] = "failed"
                stash["longrepr"] = report.longreprtext
        elif report.skipped and stash["outcome"] == "passed":
            stash["outcome"] = "skipped"

        # 3. Attach data to the report for final delivery.
        # We report on teardown, OR on setup if skipped/failed (teardown won't run or we want early info).
        # We ensure only one report is ever sent via 'reported' flag.
        should_report = False
        if report.when == "teardown":
            should_report = True
        elif report.when == "setup" and (report.skipped or report.failed):
            should_report = True

        if should_report and not stash["reported"]:
            stash["reported"] = True
            current_meta = getattr(item.config, "_test_meta_stash", {}).get(
                item.nodeid, {}
            )
            allure_data = _get_allure_result_data()

            data = {
                "start_time": getattr(item.config, "_test_start_times", {}).get(
                    item.nodeid
                ),
                "finished_at": _utc_now_iso(),
                "meta": current_meta,
                "allure_title": allure_data.get("name"),
                "allure_steps": allure_data.get("steps"),
                "name": item.nodeid,
                "outcome": stash["outcome"],
                "longrepr": stash["longrepr"],
            }

            if not hasattr(report, "user_properties"):
                report.user_properties = []
            report.user_properties.append(("testtrain_data", data))
    except Exception as e:
        print(f"\n  ⚠️  Testtrain internal error: {e}")


def pytest_runtest_logreport(report):
    """Send results to Testtrain after the phase completes."""
    config = _PLUGIN_CONFIG
    if not config or not getattr(config, "_testtrain_enabled", False):
        return

    if hasattr(config, "workerinput"):
        return

    # We report on 'teardown' for most tests.
    # However, for skipped tests, teardown might not run or we want to report early.
    # To ensure exactly one report, we report on teardown, OR on setup if it skipped/failed.
    if report.when == "teardown":
        pass
    elif report.when == "setup" and (report.skipped or report.failed):
        pass
    else:
        return

    # Extract bundled data from user_properties safely
    data = {}
    for prop in getattr(report, "user_properties", []):
        if isinstance(prop, tuple) and len(prop) == 2 and prop[0] == "testtrain_data":
            data = prop[1]
            break

    if not data:
        return

    finished_at = data.get("finished_at") or _utc_now_iso()
    started_at = data.get("start_time") or finished_at
    meta = data.get("meta") or {}
    computed_name = data.get("allure_title") or data.get("name") or report.nodeid
    description = meta.get("allure_description")
    state = _STATE_MAP.get(data.get("outcome"), "failed")

    # Capture Allure tags
    tags = []
    for label in meta.get("allure_labels", []):
        if label.get("name") == "tag":
            tags.append(label.get("value"))

    test_entry = {
        "testrunId": config._testtrain_run_id,
        "name": computed_name,
        "nodeId": report.nodeid,
        "state": state,
        "startedAt": started_at,
        "finishedAt": finished_at,
        "defects": meta.get("allure_links", []),
        "tags": tags,
        "create_tag_if_not_exists": config._testtrain_create_tag,
        "output": data.get("longrepr") or "",
    }

    if description:
        test_entry["description"] = str(description)

    if data.get("allure_steps"):
        test_entry["steps"] = data.get("allure_steps")

    max_retries = 3
    for attempt in range(max_retries + 1):
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
                error_msg = (
                    resp.json().get("message", resp.text) if resp.content else resp.text
                )
                if 400 <= resp.status_code < 500:
                    pytest.exit(
                        f"\n❌ Testtrain: Failed to send test result (Status {resp.status_code}).\n   Error: {error_msg}\n   Aborting to ensure no results are lost."
                    )
                else:
                    if attempt < max_retries:
                        time.sleep(10)
                        continue
                    pytest.exit(
                        f"\n❌ Testtrain: Failed to send test result after {max_retries + 1} attempts (Status {resp.status_code}).\n   Error: {error_msg}\n   Aborting to ensure no results are lost."
                    )
            else:
                break
        except requests.exceptions.RequestException as e:
            if attempt < max_retries:
                time.sleep(10)
                continue
            pytest.exit(
                f"\n❌ Testtrain: Connection error during reporting after {max_retries + 1} attempts: {e}\n   Aborting to ensure no results are lost."
            )


def _utc_now_iso() -> str:
    """Return current UTC time in ISO format with Z suffix."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _get_allure_result_data() -> dict:
    """Attempts to extract the current test's Allure data (name, steps)."""
    res = {"name": None, "steps": None}
    try:
        import allure_commons

        plugins = allure_commons.plugin_manager.get_plugins()
        listener = next(
            (
                p
                for p in plugins
                if type(p).__name__ == "AllureListener"
                or (
                    hasattr(p, "allure_logger") and hasattr(p.allure_logger, "get_test")
                )
            ),
            None,
        )
        if not listener:
            # Fallback for some environments where the listener might be hidden or named differently
            for p in plugins:
                if hasattr(p, "allure_logger"):
                    listener = p
                    break
        if listener:
            test_result = listener.allure_logger.get_test(None)
            if test_result:
                if test_result.name:
                    res["name"] = str(test_result.name)
                if test_result.steps:
                    res["steps"] = [_map_allure_step(s) for s in test_result.steps]
    except (ImportError, Exception):
        pass
    return res


def _map_allure_step(step) -> dict:
    """Recursively map Allure StepResult to Testtrain step format."""
    from allure_commons.model2 import Status

    output = None
    if step.statusDetails:
        output = ""
        if step.statusDetails.message:
            output += step.statusDetails.message
        if step.statusDetails.trace:
            if output:
                output += "\n"
            output += step.statusDetails.trace

    mapped = {
        "name": str(step.name) if step.name else "step",
        "is_failed": step.status in (Status.FAILED, Status.BROKEN),
        "duration": int(step.stop - step.start) if step.stop and step.start else 0,
    }
    if output:
        mapped["output"] = output
    if step.steps:
        mapped["steps"] = [_map_allure_step(s) for s in step.steps]

    return mapped


def _extract_metadata(item):
    """Internal helper to pull Allure and Pytest markers."""
    try:
        if not hasattr(item.config, "_test_meta_stash"):
            item.config._test_meta_stash = {}
        if item.nodeid not in item.config._test_meta_stash:
            item.config._test_meta_stash[item.nodeid] = {
                "markers": [],
                "allure_labels": [],
                "allure_links": [],
                "allure_description": None,
            }

        stash = item.config._test_meta_stash[item.nodeid]

        markers = []
        for m in item.iter_markers():
            markers.append({"name": m.name, "args": [str(a) for a in m.args]})
        stash["markers"] = markers

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
        stash["allure_links"] = allure_links

        try:
            import allure_commons

            listener = next(
                (
                    p
                    for p in allure_commons.plugin_manager.get_plugins()
                    if type(p).__name__ == "AllureListener"
                ),
                None,
            )
            if listener:
                res = listener.allure_logger.get_test(None)
                if res:
                    allure_labels = [
                        {
                            "name": str(getattr(label, "name", "")),
                            "value": str(getattr(label, "value", "")),
                        }
                        for label in getattr(res, "labels", [])
                    ]
                    stash["allure_labels"] = allure_labels
                    if res.description:
                        stash["allure_description"] = str(res.description)
        except Exception:
            pass

    except Exception:
        pass
