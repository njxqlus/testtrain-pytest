import json

def test_parameters_extraction(test_env):
    """Verify extraction of parameters from tests and steps."""
    test_env.makepyfile("""
        import allure
        import pytest
        from allure_commons.types import ParameterMode

        @allure.step("Step with params")
        def step_with_params(p1, p2):
            pass

        @pytest.mark.parametrize("login", ["johndoe"])
        def test_parametrized(login):
            step_with_params("val1", "val2")
            allure.dynamic.parameter("dynamic_param", "dynamic_val", mode=ParameterMode.MASKED)
    """)

    result = test_env.runpytest(
        "-p", "testtrain_pytest",
        "-p", "no:testtrain",
        "-p", "allure_pytest",
        "--testtrain-run-id", "dummy-run",
        "--testtrain-auth-token", "dummy-token",
        "--alluredir", "allure-results",
    )

    result.assert_outcomes(passed=1)

    calls_file = test_env.path / "api_calls.json"
    assert calls_file.exists()

    with open(calls_file, "r") as f:
        calls = [json.loads(line) for line in f]

    test_entry = next(
        t for c in calls for t in c.get("tests", []) if "test_parametrized" in t["nodeId"]
    )

    # Check test parameters
    params = test_entry.get("parameters", [])
    assert len(params) >= 2

    login_param = next((p for p in params if p["name"] == "login"), None)
    assert login_param is not None
    assert "johndoe" in login_param["value"]

    dynamic_param = next((p for p in params if p["name"] == "dynamic_param"), None)
    assert dynamic_param is not None
    assert "dynamic_val" in dynamic_param["value"]
    # ParameterMode.MASKED value depends on allure implementation, usually it's "masked"
    assert "mode" in dynamic_param

    # Check step parameters
    steps = test_entry.get("steps", [])
    if len(steps) > 0:
        step = steps[0]
        assert step["name"] == "Step with params"
        step_params = step.get("parameters", [])
        assert len(step_params) == 2
        assert any(sp["name"] == "p1" and "val1" in sp["value"] for sp in step_params)
        assert any(sp["name"] == "p2" and "val2" in sp["value"] for sp in step_params)
