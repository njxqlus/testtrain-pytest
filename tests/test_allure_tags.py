import json


def test_decorator(test_env):
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


def test_runtime(test_env):
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
