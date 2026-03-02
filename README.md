# testtrain-pytest

Testtrain Pytest Plugin — Real-time test result reporting.

Sends each test result to the Testtrain platform API immediately after the test finishes, enabling real-time visibility.

## Installation

You can install `pytest-testtrain` via pip from a git repository:

```bash
pip install git+https://github.com/njxqlus/testtrain-pytest.git
```

## Configuration

The plugin uses environment variables for configuration. You can set them in your environment or use a `.env` file in your project's root directory:

- `TESTTRAIN_URL` — Platform base URL (default is https://testtrain.io)
- `TESTTRAIN_RUN_ID` — ID of an existing testrun
- `TESTTRAIN_AUTH_TOKEN` — Bearer authentication token

## Usage

Once installed, the plugin works automatically without any other manipulations. Just run your tests as usual:

```bash
pytest
```

If the required environment variables are set, your test results will be reported to the Testtrain platform in real-time.

### Allure Integration

To capture Allure annotations (like titles, labels, and links), you must run your tests with the Allure plugin enabled by specifying an output directory:

```bash
pytest --alluredir=allure-results
```

Without the `--alluredir` flag, Allure metadata will not be available to the Testtrain plugin during the test run.
