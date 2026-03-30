import json


def test_allure_tags_decorator(test_env):
    """Verify that @allure.tag is correctly captured."""
    test_env.makepyfile("""
        import allure
        import pytest

        @allure.tag("NewUI", "Essentials", "Authentication")
        def test_authentication():
            assert True
    """)

    res = test_env.runpytest_subprocess(
        "-p",
        "testtrain_sandbox",
        "-p",
        "no:testtrain",
        "-p",
        "allure_pytest",
        "--testtrain-run-id",
        "dummy-run",
        "--testtrain-auth-token",
        "dummy-token",
        "--alluredir",
        "allure-results",
    )

    res.assert_outcomes(passed=1)

    calls_file = test_env.path / "api_calls.json"
    assert calls_file.exists()
    calls = [json.loads(line) for line in calls_file.read_text().splitlines()]

    # Exactly one API call should be made for this test
    assert len(calls) == 1

    test_entry = next(
        t
        for c in calls
        for t in c.get("tests", [])
        if "test_authentication" in t["nodeId"]
    )

    assert "tags" in test_entry
    assert set(test_entry["tags"]) == {"NewUI", "Essentials", "Authentication"}
    assert test_entry.get("create_tag_if_not_exists") is True

def test_allure_tags_runtime(test_env):
    """Verify that allure.dynamic.tag is correctly captured."""
    test_env.makepyfile("""
        import allure
        import pytest

        def test_authentication():
            allure.dynamic.tag("NewUI", "Essentials", "Authentication")
            assert True
    """)

    res = test_env.runpytest_subprocess(
        "-p",
        "testtrain_sandbox",
        "-p",
        "no:testtrain",
        "-p",
        "allure_pytest",
        "--testtrain-run-id",
        "dummy-run",
        "--testtrain-auth-token",
        "dummy-token",
        "--alluredir",
        "allure-results",
    )

    res.assert_outcomes(passed=1)

    calls_file = test_env.path / "api_calls.json"
    assert calls_file.exists()
    calls = [json.loads(line) for line in calls_file.read_text().splitlines()]

    assert len(calls) == 1

    test_entry = next(
        t
        for c in calls
        for t in c.get("tests", [])
        if "test_authentication" in t["nodeId"]
    )

    assert "tags" in test_entry
    assert set(test_entry["tags"]) == {"NewUI", "Essentials", "Authentication"}
    assert test_entry.get("create_tag_if_not_exists") is True

def test_create_tag_flag_disabled(test_env):
    """Verify that --testtrain-create-tag=false is correctly captured."""
    test_env.makepyfile("""
        import allure
        import pytest

        @allure.tag("NewUI")
        def test_authentication():
            assert True
    """)

    res = test_env.runpytest_subprocess(
        "-p",
        "testtrain_sandbox",
        "-p",
        "no:testtrain",
        "-p",
        "allure_pytest",
        "--testtrain-run-id",
        "dummy-run",
        "--testtrain-auth-token",
        "dummy-token",
        "--testtrain-create-tag",
        "false",
        "--alluredir",
        "allure-results",
    )

    res.assert_outcomes(passed=1)

    calls_file = test_env.path / "api_calls.json"
    assert calls_file.exists()
    calls = [json.loads(line) for line in calls_file.read_text().splitlines()]

    assert len(calls) == 1

    test_entry = next(
        t
        for c in calls
        for t in c.get("tests", [])
        if "test_authentication" in t["nodeId"]
    )

    assert test_entry.get("create_tag_if_not_exists") is False

def test_teardown_failure(test_env):
    """Verify that teardown failures are correctly reported."""
    test_env.makepyfile("""
        import pytest

        @pytest.fixture
        def failing_teardown():
            yield
            raise RuntimeError("Teardown failed")

        def test_failing_teardown(failing_teardown):
            assert True
    """)

    res = test_env.runpytest_subprocess(
        "-p",
        "testtrain_sandbox",
        "-p",
        "no:testtrain",
        "--testtrain-run-id",
        "dummy-run",
        "--testtrain-auth-token",
        "dummy-token",
    )

    # In pytest, a teardown failure results in passed=1 and error=1
    res.assert_outcomes(passed=1, errors=1)

    calls_file = test_env.path / "api_calls.json"
    assert calls_file.exists()
    calls = [json.loads(line) for line in calls_file.read_text().splitlines()]

    assert len(calls) == 1
    test_entry = calls[0]["tests"][0]
    assert test_entry["state"] == "failed"

def test_skipped_test(test_env):
    """Verify that skipped tests are correctly reported."""
    test_env.makepyfile("""
        import pytest

        @pytest.mark.skip(reason="Testing skip")
        def test_skipped():
            assert True
    """)

    res = test_env.runpytest_subprocess(
        "-p",
        "testtrain_sandbox",
        "-p",
        "no:testtrain",
        "--testtrain-run-id",
        "dummy-run",
        "--testtrain-auth-token",
        "dummy-token",
    )

    res.assert_outcomes(skipped=1)

    calls_file = test_env.path / "api_calls.json"
    assert calls_file.exists()
    calls = [json.loads(line) for line in calls_file.read_text().splitlines()]

    assert len(calls) == 1
    test_entry = calls[0]["tests"][0]
    assert test_entry["state"] == "skipped"

def test_failure_immediately_reported_but_only_once(test_env):
    """Verify that a failure in the test body is reported at the end and only once."""
    test_env.makepyfile("""
        def test_failure():
            assert False
    """)

    res = test_env.runpytest_subprocess(
        "-p",
        "testtrain_sandbox",
        "-p",
        "no:testtrain",
        "--testtrain-run-id",
        "dummy-run",
        "--testtrain-auth-token",
        "dummy-token",
    )

    res.assert_outcomes(failed=1)

    calls_file = test_env.path / "api_calls.json"
    assert calls_file.exists()
    calls = [json.loads(line) for line in calls_file.read_text().splitlines()]

    assert len(calls) == 1
    test_entry = calls[0]["tests"][0]
    assert test_entry["state"] == "failed"
