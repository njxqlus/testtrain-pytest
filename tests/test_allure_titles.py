import json


def test_decorator(test_env):
    """Decorator: @allure.title on test function."""
    test_env.makepyfile("""
        import allure
        import pytest

        @allure.title("Test Authentication")
        def test_authentication():
            assert True
    """)

    # Run pytest. We load our local plugin and disable the installed one
    result = test_env.runpytest(
        "-p",
        "testtrain_pytest",
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

    result.assert_outcomes(passed=1)

    # Verify name in the first captured API call
    calls_file = test_env.path / "api_calls.json"
    assert calls_file.exists()
    calls = [json.loads(line) for line in calls_file.read_text().splitlines()]

    # Find the 'tests' entry
    test_entry = next(
        t
        for c in calls
        for t in c.get("tests", [])
        if "test_authentication" in t["nodeId"]
    )
    assert test_entry["name"] == "Test Authentication"


def test_fixture_decorator(test_env):
    """Decorator on fixture: @allure.title on fixture."""
    test_env.makepyfile("""
        import allure
        import pytest

        @pytest.fixture()
        @allure.title("Prepare for the test")
        def my_fixture():
            yield

        def test_with_my_fixture(my_fixture):
            assert True
    """)

    result = test_env.runpytest(
        "-p",
        "testtrain_pytest",
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

    result.assert_outcomes(passed=1)

    calls_file = test_env.path / "api_calls.json"
    assert calls_file.exists()
    calls = [json.loads(line) for line in calls_file.read_text().splitlines()]

    test_entry = next(
        t
        for c in calls
        for t in c.get("tests", [])
        if "test_with_my_fixture" in t["nodeId"]
    )
    assert (
        test_entry["name"] == "test_with_my_fixture"
        or "test_with_my_fixture" in test_entry["name"]
    )


def test_runtime_api(test_env):
    """Runtime API: allure.dynamic.title."""
    test_env.makepyfile("""
        import allure
        import pytest

        def test_authentication():
            allure.dynamic.title("Dynamic Test Title")
            assert True
    """)

    result = test_env.runpytest(
        "-p",
        "testtrain_pytest",
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

    result.assert_outcomes(passed=1)

    calls_file = test_env.path / "api_calls.json"
    assert calls_file.exists()
    calls = [json.loads(line) for line in calls_file.read_text().splitlines()]

    test_entry = next(
        t
        for c in calls
        for t in c.get("tests", [])
        if "test_authentication" in t["nodeId"]
    )
    assert test_entry["name"] == "Dynamic Test Title"
