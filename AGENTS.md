# Project: testtrain-pytest

## Goal
A `pytest` plugin that collects test results and **Allure metadata**  and sends them to the **Testtrain API** in real-time as tests complete.

## Testing Strategy
The project uses `pytester` for integration tests.
- **Isolation**: Each test runs in a temporary environment using the `pytester` fixture.
- **Mocking**: API calls to `requests.post` are intercepted via `monkeypatch`.
- **Verification**: Sent data is written to a local `api_calls.json` within the sandbox and then verified for correctness (e.g., node IDs, Allure titles).
