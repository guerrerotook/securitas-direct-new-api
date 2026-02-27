# Integration Test Framework Design

## Goal

Add pytest-based integration tests for `ApiManager` with mocked API responses, focusing on the authentication flow (login, refresh, token management).

## Stack

- **pytest** + **pytest-asyncio** for async test execution
- **unittest.mock** (`AsyncMock`, `patch`) to mock `_execute_request`
- **PyJWT** (already a dependency) to generate real JWT tokens with known `exp` claims

No new runtime dependencies. Test dependencies: `pytest`, `pytest-asyncio`.

## Mock Strategy

Patch `ApiManager._execute_request` to return canned JSON dicts. This tests all response parsing, JWT decoding, token storage, and error handling without hitting the network.

Real JWT tokens are generated in fixtures using PyJWT so `jwt.decode()` in the production code works naturally — no need to also mock the JWT library.

## Structure

```
tests/
  conftest.py          # ApiManager factory, fake JWT helper, common fixtures
  test_auth.py         # login, refresh_token, _check_authentication_token, validate_device
```

## Initial Test Coverage

### login()
- Stores hash, refreshToken, login_timestamp, decodes JWT expiry
- 2FA response triggers Login2FAError
- Error responses raise LoginError
- Null hash sets login_timestamp (2FA path)

### refresh_token()
- Success: stores new hash, refreshToken, login_timestamp, expiry
- Returns False on non-OK res
- Returns False on missing hash
- Returns False on JWT decode failure

### _check_authentication_token()
- Tries refresh first when refresh_token_value is set, falls back to login on failure
- Catches broad exceptions from refresh and falls back to login
- Calls login directly when no refresh_token_value

### validate_device()
- Stores hash, refreshToken, decodes JWT expiry on success
- JWT decode failure logs warning, doesn't crash
