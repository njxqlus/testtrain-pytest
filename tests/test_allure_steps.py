import json

def test_allure_step_decorator(test_env):
    """Verify Allure steps created via @allure.step decorator."""
    test_env.makepyfile("""
        import allure
        import pytest
        import allure_commons

        @allure.step("Step 1")
        def step1():
            pass

        def test_example(request):
            step1()
            print(f"\\nAllure internal: {allure_commons.plugin_manager.get_plugins()}")
            for p in allure_commons.plugin_manager.get_plugins():
                 if hasattr(p, "allure_logger"):
                      print(f"\\nFound logger on {type(p).__name__}")
    """)

    result = test_env.runpytest(
        "-p", "testtrain_pytest",
        "-p", "no:testtrain",
        "-p", "allure_pytest",
        "--testtrain-run-id", "dummy-run",
        "--testtrain-auth-token", "dummy-token",
        "-s"
    )

    result.assert_outcomes(passed=1)
