import json


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
