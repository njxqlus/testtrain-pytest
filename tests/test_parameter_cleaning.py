import json

def test_allure_parameter_cleaning(test_env):
    """Verify that allure parameters are cleaned of wrapping single quotes if they contain content."""
    test_env.makepyfile("""
        import allure
        import pytest

        def test_quoting():
            allure.dynamic.parameter("key", "id_rsa2")
            allure.dynamic.parameter("empty", "")
            allure.dynamic.parameter("single_quote", "'")
            allure.dynamic.parameter("just_starts", "'start")
            allure.dynamic.parameter("just_ends", "end'")
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

    with open(test_env.path / "api_calls.json", "r") as f:
        lines = f.readlines()
        calls = [json.loads(line) for line in lines if line.strip()]

    test_entry = next(
        (t for c in calls for t in c.get("tests", []) if "test_quoting" in t["nodeId"]),
        None,
    )
    params = {p["name"]: p["value"] for p in test_entry.get("parameters", [])}

    # Desired behavior:
    assert params["key"] == "id_rsa2"
    assert params["empty"] == "''"
    assert params["single_quote"] == "'"
    assert params["just_starts"] == "'start"
    assert params["just_ends"] == "end'"
