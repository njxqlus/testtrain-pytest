import json


def test_no_description_omitted(test_env):
    """Verify that the description field is omitted if not provided."""
    test_env.makepyfile("""
        def test_no_desc():
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

    res.assert_outcomes(passed=1)

    calls_file = test_env.path / "api_calls.json"
    assert calls_file.exists()
    calls = [json.loads(line) for line in calls_file.read_text().splitlines()]

    assert len(calls) == 1
    test_entry = calls[0]["tests"][0]

    # The key should be missing entirely
    assert "description" not in test_entry
