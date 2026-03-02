# testtrain-pytest

Testtrain Pytest Plugin — Real-time test result reporting.

Sends each test result to the Testtrain platform API immediately after the test finishes, enabling real-time visibility into your test runs.

## Installation

You can install `testtrain-pytest` via pip:

```bash
pip install git+https://github.com/njxqlus/testtrain-pytest.git
```

## Configuration

The plugin requires two mandatory settings:
- **Run ID**: The UUID of an existing test run in Testtrain.
- **Auth Token**: Your bearer authentication token.

You can configure these using environment variables, command-line arguments, or your `pytest.ini` file.

### Option 1: Environment Variables (Recommended)

Set these in your shell before running pytest. This is standard for CI/CD environments.

```bash
export TESTTRAIN_RUN_ID="your-run-uuid"
export TESTTRAIN_AUTH_TOKEN="your-token"
pytest
```

> [!TIP]
> If you want to use a `.env` file, you should install `pytest-dotenv` separately as this plugin does not load `.env` files automatically.

### Option 2: Command Line Arguments

Pass them directly to the `pytest` command.

```bash
pytest --testtrain-run-id=your-run-uuid --testtrain-auth-token=your-token
```

### Option 3: Configuration File (`pytest.ini` or `pyproject.toml`)

Add them to your project's configuration file.

**pytest.ini**:
```ini
[pytest]
testtrain_run_id = your-run-uuid
testtrain_auth_token = your-token
```

**pyproject.toml**:
```toml
[tool.pytest.ini_options]
testtrain_run_id = "your-run-uuid"
testtrain_auth_token = "your-token"
```

## Usage

Once configured, the plugin works automatically. If the required configuration is missing, the plugin will remain inactive and won't affect your tests.

### Allure Integration

To capture Allure metadata (like custom titles and labels), you must run your tests with the Allure plugin enabled:

```bash
pytest --alluredir=allure-results
```

Without the `--alluredir` flag, Allure metadata will not be available to the Testtrain plugin during the test run.
