import json


def test_pytest_standard_parameter(test_env):
    """Verify that normal pytest parameterization is captured."""
    test_env.makepyfile("""
        import pytest
        @pytest.mark.parametrize("input_val", ["hello_world"])
        def test_standard(input_val):
            pass
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
        (
            t
            for c in calls
            for t in c.get("tests", [])
            if "test_standard" in t["nodeId"]
        ),
        None,
    )
    params = test_entry.get("parameters", [])
    assert any(p["name"] == "input_val" and "hello_world" in p["value"] for p in params)


def test_allure_dynamic_parameter(test_env):
    """Verify that allure.dynamic.parameter is captured."""
    test_env.makepyfile("""
        import allure
        def test_dynamic():
            allure.dynamic.parameter("api_version", "v2")
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
        (t for c in calls for t in c.get("tests", []) if "test_dynamic" in t["nodeId"]),
        None,
    )
    params = test_entry.get("parameters", [])
    assert any(p["name"] == "api_version" and "v2" in p["value"] for p in params)


def test_step_parameters(test_env):
    """Verify that parameters in allure steps are captured."""
    test_env.makepyfile("""
        import allure
        @allure.step("Execution Step")
        def my_step(arg1):
            pass
            
        def test_step_params():
            my_step("secret_data")
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
        (
            t
            for c in calls
            for t in c.get("tests", [])
            if "test_step_params" in t["nodeId"]
        ),
        None,
    )
    step = test_entry["steps"][0]
    assert step["name"] == "Execution Step"
    assert any(
        p["name"] == "arg1" and "secret_data" in p["value"] for p in step["parameters"]
    )


def test_parameter_modes_and_hidden_filtering(test_env):
    """
    Verify different parameter modes.
    Masked and Default should be sent, Hidden should be filtered out.
    """
    test_env.makepyfile("""
        import allure
        from allure_commons.types import ParameterMode
        
        def test_modes():
            allure.dynamic.parameter("visible", "val1", mode=ParameterMode.DEFAULT)
            allure.dynamic.parameter("secret", "val2", mode=ParameterMode.MASKED)
            allure.dynamic.parameter("internal", "val3", mode=ParameterMode.HIDDEN)
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
        (t for c in calls for t in c.get("tests", []) if "test_modes" in t["nodeId"]),
        None,
    )
    params = test_entry.get("parameters", [])

    # Check that visible and secret are present
    assert any(p["name"] == "visible" and "val1" in p["value"] for p in params)
    assert any(p["name"] == "secret" and "val2" in p["value"] for p in params)

    # Check that internal (hidden) is NOT present
    assert not any(p["name"] == "internal" for p in params), (
        f"Hidden parameter 'internal' should not be in {params}"
    )

    # Verify modes are sent correctly
    secret_param = next(p for p in params if p["name"] == "secret")
    assert (
        "masked" in secret_param["mode"].lower()
        or secret_param["mode"] == "ParameterMode.MASKED"
    )
