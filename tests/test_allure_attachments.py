import json


def _collect_step_attachment_fields(steps):
    fields = set()
    for step in steps:
        for attachment in step.get("attachments", []):
            fields.add(attachment["field"])
        fields.update(_collect_step_attachment_fields(step.get("steps", [])))
    return fields


def test_allure_test_and_step_attachments_are_sent(test_env):
    test_env.makepyfile("""
        import allure

        def test_attachments():
            allure.attach("test-level log", name="test_log", attachment_type=allure.attachment_type.TEXT)
            with allure.step("Step with attachment"):
                allure.attach("step-level log", name="step_log", attachment_type=allure.attachment_type.TEXT)
    """)

    result = test_env.runpytest(
        "-p",
        "testtrain_pytest",
        "-p",
        "no:testtrain",
        "-p",
        "allure_pytest",
        "--alluredir",
        "allure-results",
        "--testtrain-run-id",
        "dummy-run",
        "--testtrain-auth-token",
        "dummy-token",
    )

    result.assert_outcomes(passed=1)

    calls_file = test_env.path / "api_calls.json"
    assert calls_file.exists()
    calls = [json.loads(line) for line in calls_file.read_text().splitlines()]

    call_payload = next(
        c
        for c in calls
        if any("test_attachments" in t["nodeId"] for t in c.get("tests", []))
    )
    test_entry = next(
        t for t in call_payload.get("tests", []) if "test_attachments" in t["nodeId"]
    )

    assert "attachments" in test_entry
    assert len(test_entry["attachments"]) == 1

    steps = test_entry.get("steps", [])
    assert len(steps) == 1
    assert steps[0]["name"] == "Step with attachment"
    assert "attachments" in steps[0]
    assert len(steps[0]["attachments"]) == 1

    file_fields = set(call_payload.get("__files__", []))
    assert len(file_fields) == 2

    referenced_fields = {a["field"] for a in test_entry.get("attachments", [])}
    referenced_fields.update(_collect_step_attachment_fields(steps))
    assert referenced_fields == file_fields


def test_nested_step_attachments_are_sent(test_env):
    test_env.makepyfile("""
        import allure

        def test_nested_step_attachments():
            with allure.step("Parent step"):
                allure.attach("parent", name="parent_log", attachment_type=allure.attachment_type.TEXT)
                with allure.step("Child step"):
                    allure.attach("child", name="child_log", attachment_type=allure.attachment_type.TEXT)
    """)

    result = test_env.runpytest(
        "-p",
        "testtrain_pytest",
        "-p",
        "no:testtrain",
        "-p",
        "allure_pytest",
        "--alluredir",
        "allure-results",
        "--testtrain-run-id",
        "dummy-run",
        "--testtrain-auth-token",
        "dummy-token",
    )

    result.assert_outcomes(passed=1)

    calls_file = test_env.path / "api_calls.json"
    calls = [json.loads(line) for line in calls_file.read_text().splitlines()]
    call_payload = next(
        c
        for c in calls
        if any(
            "test_nested_step_attachments" in t["nodeId"] for t in c.get("tests", [])
        )
    )
    test_entry = next(
        t
        for t in call_payload.get("tests", [])
        if "test_nested_step_attachments" in t["nodeId"]
    )

    steps = test_entry.get("steps", [])
    assert len(steps) == 1
    assert steps[0]["name"] == "Parent step"
    assert len(steps[0].get("steps", [])) == 1
    assert steps[0]["steps"][0]["name"] == "Child step"

    referenced_fields = _collect_step_attachment_fields(steps)
    assert len(referenced_fields) == 2
    assert referenced_fields == set(call_payload.get("__files__", []))


def test_non_file_attachments_are_skipped(test_env):
    test_env.makepyfile("""
        import testtrain_pytest

        def test_non_file_attachment(monkeypatch, tmp_path):
            bad_attachment_path = tmp_path / "not-a-file"
            bad_attachment_path.mkdir()
            monkeypatch.setattr(
                testtrain_pytest,
                "_get_allure_result_data",
                lambda: {
                    "name": None,
                    "steps": None,
                    "parameters": None,
                    "attachments": [{"source": str(bad_attachment_path), "name": "bad"}],
                },
            )
            assert True
    """)

    result = test_env.runpytest(
        "-p",
        "testtrain_pytest",
        "-p",
        "no:testtrain",
        "--testtrain-run-id",
        "dummy-run",
        "--testtrain-auth-token",
        "dummy-token",
    )

    result.assert_outcomes(passed=1)

    calls_file = test_env.path / "api_calls.json"
    calls = [json.loads(line) for line in calls_file.read_text().splitlines()]
    call_payload = next(
        c
        for c in calls
        if any("test_non_file_attachment" in t["nodeId"] for t in c.get("tests", []))
    )
    test_entry = next(
        t
        for t in call_payload.get("tests", [])
        if "test_non_file_attachment" in t["nodeId"]
    )
    assert "__files__" not in call_payload
    assert "attachments" not in test_entry
