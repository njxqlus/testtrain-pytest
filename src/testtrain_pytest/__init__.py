import json
import mimetypes
import os
import time
from datetime import datetime, timezone
from pathlib import Path

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
                "parameters": allure_data.get("parameters"),
                "attachments": allure_data.get("attachments"),
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

    if data.get("parameters"):
        test_entry["parameters"] = data.get("parameters")

    if data.get("attachments"):
        test_entry["attachments"] = data.get("attachments")

    alluredir = getattr(config.option, "allure_report_dir", None)
    opened_multipart_files = []

    max_retries = 3
    try:
        for attempt in range(max_retries + 1):
            try:
                try:
                    multipart_payload = _build_multipart_payload(test_entry, alluredir)
                    payload_entry = multipart_payload.get("entry", test_entry)
                    opened_multipart_files = multipart_payload.get("files", [])
                except (OSError, ValueError):
                    multipart_payload = None
                    payload_entry = test_entry
                    opened_multipart_files = []
                headers = {
                    "Authorization": f"Bearer {config._testtrain_auth_token}",
                }
                if multipart_payload and opened_multipart_files:
                    _rewind_multipart_files(opened_multipart_files)
                    resp = requests.post(
                        f"{config._testtrain_url}/api/tests",
                        data={"meta": json.dumps({"tests": [payload_entry]})},
                        files=opened_multipart_files,
                        headers=headers,
                        timeout=10,
                    )
                else:
                    resp = requests.post(
                        f"{config._testtrain_url}/api/tests",
                        json={"tests": [payload_entry]},
                        headers={**headers, "Content-Type": "application/json"},
                        timeout=10,
                    )
                if not resp.ok:
                    error_msg = (
                        resp.json().get("message", resp.text)
                        if resp.content
                        else resp.text
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
    finally:
        _close_multipart_files(opened_multipart_files)


def _utc_now_iso() -> str:
    """Return current UTC time in ISO format with Z suffix."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _smart_strip_quotes(val: str) -> str:
    """
    Remove wrapping single quotes from a string if it has content inside.
    Allure often wraps parameter values in extra single quotes (e.g. "'val'").
    We strip them ONLY if the string is longer than 2 characters and starts/ends with '.
    """
    if len(val) > 2 and val.startswith("'") and val.endswith("'"):
        return val[1:-1]
    return val


def _get_allure_result_data() -> dict:
    """Attempts to extract the current test's Allure data (name, steps, parameters)."""
    res = {"name": None, "steps": None, "parameters": None, "attachments": None}
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
                test_name = getattr(test_result, "name", None)
                if test_name:
                    res["name"] = str(test_name)

                test_parameters = getattr(test_result, "parameters", [])
                if test_parameters:
                    res["parameters"] = [
                        {
                            "name": getattr(p, "name", "param"),
                            "value": _smart_strip_quotes(str(getattr(p, "value", ""))),
                            "mode": str(getattr(p, "mode", "default") or "default"),
                        }
                        for p in test_parameters
                        if str(getattr(p, "mode", "default") or "default") != "hidden"
                    ]

                test_steps = getattr(test_result, "steps", [])
                mapped_test_steps = [_map_allure_step(s) for s in test_steps]
                if mapped_test_steps:
                    res["steps"] = mapped_test_steps

                try:
                    fixture_steps = _collect_allure_fixture_steps(listener, test_result)
                    if fixture_steps:
                        res["steps"] = _wrap_allure_steps_with_lifecycle(
                            fixture_steps.get("setup", []),
                            mapped_test_steps,
                            fixture_steps.get("teardown", []),
                        )
                except Exception:
                    pass
                test_attachments = getattr(test_result, "attachments", [])
                if test_attachments:
                    attachments = [_map_allure_attachment(a) for a in test_attachments]
                    res["attachments"] = [
                        attachment for attachment in attachments if attachment
                    ]
    except (ImportError, Exception):
        pass
    return res


def _collect_allure_fixture_steps(listener, test_result):
    logger = getattr(listener, "allure_logger", None)
    test_uuid = getattr(test_result, "uuid", None)
    if not logger or not test_uuid:
        return None

    get_item = getattr(logger, "get_item", None)
    if not callable(get_item):
        return None

    items = getattr(logger, "_items", None)
    if not items:
        return None

    try:
        item_uuids = list(items)
    except TypeError:
        return None

    setup_steps = []
    teardown_steps = []
    for item_uuid in item_uuids:
        try:
            container = get_item(item_uuid)
        except Exception:
            continue
        if not container:
            continue
        children = getattr(container, "children", [])
        if test_uuid not in children:
            continue

        befores = getattr(container, "befores", [])
        if befores:
            setup_steps.extend(_map_allure_step(step) for step in befores)

        afters = getattr(container, "afters", [])
        if afters:
            teardown_steps.extend(_map_allure_step(step) for step in afters)

    if not setup_steps and not teardown_steps:
        return None
    return {"setup": setup_steps, "teardown": teardown_steps}


def _allure_step_tree_is_failed(steps) -> bool:
    for step in steps or []:
        if step.get("is_failed"):
            return True
        if _allure_step_tree_is_failed(step.get("steps") or []):
            return True
    return False


def _allure_step_tree_duration(steps) -> int:
    total = 0
    for step in steps or []:
        total += int(step.get("duration") or 0)
        total += _allure_step_tree_duration(step.get("steps") or [])
    return total


def _wrap_allure_steps_with_lifecycle(setup_steps, body_steps, teardown_steps):
    def _build_group(name, grouped_steps):
        step_list = grouped_steps or []
        return {
            "name": name,
            "is_failed": _allure_step_tree_is_failed(step_list),
            "duration": _allure_step_tree_duration(step_list),
            "steps": step_list,
        }

    return [
        _build_group("Set up", setup_steps),
        _build_group("Test body", body_steps),
        _build_group("Tear down", teardown_steps),
    ]


def _map_allure_step(step) -> dict:
    """Recursively map Allure StepResult to Testtrain step format."""
    from allure_commons.model2 import Status

    output = None
    status_details = getattr(step, "statusDetails", None)
    if status_details:
        output = ""
        msg = getattr(status_details, "message", None)
        if msg:
            output += str(msg)
        trace = getattr(status_details, "trace", None)
        if trace:
            if output:
                output += "\n"
            output += str(trace)

    step_name = getattr(step, "name", "step")
    step_status = getattr(step, "status", Status.PASSED)
    step_start = getattr(step, "start", 0)
    step_stop = getattr(step, "stop", 0)

    mapped = {
        "name": str(step_name),
        "is_failed": step_status in (Status.FAILED, Status.BROKEN),
        "duration": int(step_stop - step_start) if step_stop and step_start else 0,
    }
    if output:
        mapped["output"] = output

    step_parameters = getattr(step, "parameters", [])
    if step_parameters:
        mapped["parameters"] = [
            {
                "name": getattr(p, "name", "param"),
                "value": _smart_strip_quotes(str(getattr(p, "value", ""))),
                "mode": str(getattr(p, "mode", "default") or "default"),
            }
            for p in step_parameters
            if str(getattr(p, "mode", "default") or "default") != "hidden"
        ]

    step_substeps = getattr(step, "steps", [])
    if step_substeps:
        mapped["steps"] = [_map_allure_step(s) for s in step_substeps]

    step_attachments = getattr(step, "attachments", [])
    if step_attachments:
        attachments = [_map_allure_attachment(a) for a in step_attachments]
        attachments = [attachment for attachment in attachments if attachment]
        if attachments:
            mapped["attachments"] = attachments

    return mapped


def _map_allure_attachment(attachment) -> dict:
    source = getattr(attachment, "source", None)
    if not source:
        return {}
    mapped = {"source": str(source)}
    attachment_name = getattr(attachment, "name", None)
    if attachment_name:
        mapped["name"] = str(attachment_name)
    attachment_type = getattr(attachment, "type", None)
    if attachment_type:
        mapped["type"] = str(attachment_type)
    return mapped


def _build_multipart_payload(entry: dict, alluredir):
    files = []
    used_fields = set()
    transformed_entry = dict(entry)

    test_attachments = entry.get("attachments", [])
    if test_attachments:
        mapped_attachments = _collect_attachments(
            test_attachments, alluredir, files, used_fields, "test_attachment"
        )
        if mapped_attachments:
            transformed_entry["attachments"] = mapped_attachments
        else:
            transformed_entry.pop("attachments", None)

    steps = entry.get("steps", [])
    if steps:
        transformed_entry["steps"] = [
            _transform_step_attachments(s, alluredir, files, used_fields, f"step_{idx}")
            for idx, s in enumerate(steps, start=1)
        ]

    return {"entry": transformed_entry, "files": files}


def _transform_step_attachments(step, alluredir, files, used_fields, prefix):
    transformed = {k: v for k, v in step.items() if k not in {"attachments", "steps"}}
    step_attachments = step.get("attachments", [])
    if step_attachments:
        mapped_attachments = _collect_attachments(
            step_attachments, alluredir, files, used_fields, f"{prefix}_attachment"
        )
        if mapped_attachments:
            transformed["attachments"] = mapped_attachments
    child_steps = step.get("steps", [])
    if child_steps:
        transformed["steps"] = [
            _transform_step_attachments(
                child_step, alluredir, files, used_fields, f"{prefix}_{idx}"
            )
            for idx, child_step in enumerate(child_steps, start=1)
        ]
    return transformed


def _collect_attachments(attachments, alluredir, files, used_fields, prefix):
    mapped = []
    for idx, attachment in enumerate(attachments, start=1):
        attachment_data = attachment or {}
        source = str(attachment_data.get("source", "")).strip()
        if not source:
            continue
        path = _resolve_attachment_path(source, alluredir)
        if not path:
            continue
        if not path.is_file():
            continue

        field = _make_unique_field_name(
            attachment_data.get("name") or path.stem or f"{prefix}_{idx}",
            used_fields,
        )
        filename = path.name
        content_type = attachment_data.get("type") or mimetypes.guess_type(filename)[0]
        try:
            file_handle = path.open("rb")
        except OSError:
            continue
        files.append(
            (field, (filename, file_handle, content_type or "application/octet-stream"))
        )
        mapped.append({"field": field})
    return mapped


def _resolve_attachment_path(source, alluredir):
    source_path = Path(source)
    if source_path.is_absolute() and source_path.exists():
        return source_path
    if alluredir:
        allure_path = Path(alluredir) / source
        if allure_path.exists():
            return allure_path
    cwd_path = Path.cwd() / source
    if cwd_path.exists():
        return cwd_path
    return None


def _make_unique_field_name(raw_name, used_fields):
    safe_name = "".join(
        ch if (ch.isalnum() or ch in {"_", "-"}) else "_" for ch in str(raw_name)
    ).strip("_")
    base = safe_name or "attachment"
    field = base
    counter = 2
    while field in used_fields:
        field = f"{base}_{counter}"
        counter += 1
    used_fields.add(field)
    return field


def _rewind_multipart_files(files):
    for _, file_data in files:
        if not isinstance(file_data, tuple) or len(file_data) < 2:
            continue
        fileobj = file_data[1]
        if hasattr(fileobj, "seek"):
            try:
                fileobj.seek(0)
            except (OSError, ValueError):
                pass


def _close_multipart_files(files):
    for _, file_data in files:
        if not isinstance(file_data, tuple) or len(file_data) < 2:
            continue
        fileobj = file_data[1]
        if hasattr(fileobj, "close"):
            try:
                fileobj.close()
            except OSError:
                pass


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
                    description = getattr(res, "description", None)
                    if description:
                        stash["allure_description"] = str(description)
        except Exception:
            pass

    except Exception:
        pass
