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
