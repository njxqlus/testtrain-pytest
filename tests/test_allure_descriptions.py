import json


def test_decorator(test_env):
    """Verify that @allure.description is correctly captured."""
    test_env.makepyfile("""
        import allure
        import pytest

        @allure.description('''
            This test attempts to log into the website using a login and a password. Fails if any error happens.

            Note that this test does not test 2-Factor Authentication.
        ''')
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

    test_entry = next(
        t
        for c in calls
        for t in c.get("tests", [])
        if "test_authentication" in t["nodeId"]
    )
    assert "description" in test_entry
    assert "attempts to log into the website" in test_entry["description"]
    assert "does not test 2-Factor Authentication" in test_entry["description"]


def test_runtime_api(test_env):
    """Verify that allure.dynamic.description() is correctly captured."""
    test_env.makepyfile("""
        import allure
        import pytest

        def test_authentication():
            allure.dynamic.description('''
                Runtime dynamic description text.
            ''')
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

    test_entry = next(
        t
        for c in calls
        for t in c.get("tests", [])
        if "test_authentication" in t["nodeId"]
    )
    assert "description" in test_entry
    assert "Runtime dynamic description text" in test_entry["description"]


def test_docstring(test_env):
    """Verify that docstring is captured by Allure/Testtrain."""
    test_env.makepyfile("""
        import allure
        import pytest

        def test_authentication():
            '''
            This is a docstring description.
            It should be captured by Allure automatically.
            '''
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

    test_entry = next(
        t
        for c in calls
        for t in c.get("tests", [])
        if "test_authentication" in t["nodeId"]
    )
    assert "description" in test_entry
    assert "This is a docstring description" in test_entry["description"]
