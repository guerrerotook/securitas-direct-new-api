# Securitas API: Unsupported Command Behavior

## Problem

When we send a compound command like `DARM1DARMPERI` that the panel doesn't support, Securitas doesn't reject it upfront. Instead:

1. `xSDisarmPanel` mutation returns `res: "OK"` — command accepted
2. `DisarmStatus` polling returns `res: "WAIT"` for **~60 seconds** (30 polls at 2s intervals)
3. Finally returns an error:

```json
{
  "res": "ERROR",
  "msg": "alarm-manager.error_protom_session",
  "error": {
    "code": "alarm-manager.error_protom_session",
    "type": "TECHNICAL_ERROR",
    "allowForcing": false,
    "exceptionsNumber": null,
    "referenceId": null
  },
  "protomResponse": null,
  "protomResponseDate": "2026-03-06T10:55:30Z"
}
```

## Observed Behavior

- The alarm **does actually disarm** — subsequent `CheckAlarmStatus` shows `protomResponse: "D"` (disarmed). The panel appears to execute the `DARM1` portion but can't confirm through the normal polling channel.
- The `protomResponse` in the `DisarmStatus` result is **null**.

## Fix (implemented)

This bug is now fixed in two stages:

1. **Detection**: After `_poll_operation` returns, `arm_alarm()` and `disarm_alarm()` in `apimanager.py` check for `res: "ERROR"` with a non-`NON_BLOCKING` error type (e.g. `TECHNICAL_ERROR`). When detected, they raise `SecuritasDirectError` (without `http_status`, distinguishing it from GraphQL validation errors).

2. **Handling in `_execute_step()`**: TECHNICAL_ERROR is re-raised immediately (like 403 WAF and 409 busy errors) without trying alternative commands — the panel is having communication issues, so alternatives would likely also fail. The command is NOT marked as unsupported since the error is transient.

Previously, the ERROR result passed through silently — `_poll_operation` returned it (not WAIT), `disarm_alarm()` wrapped it in a `DisarmStatus` without raising, and the fallback logic never fired. The user waited 60 seconds for nothing.

## GraphQL Enum Validation

The `DisarmCodeRequest` (and `ArmCodeRequest`) enums are validated server-side by Securitas's GraphQL layer. Sending a completely unknown command like `TEST` gets rejected immediately:

```json
{
  "errors": [{
    "message": "Variable \"$request\" got invalid value \"TEST\"; Value \"TEST\" does not exist in \"DisarmCodeRequest\" enum.",
    "extensions": {"code": "BAD_USER_INPUT"},
    "data": {}
  }]
}
```

This means `DARM1DARMPERI` **is** a valid enum value in the schema — the GraphQL layer accepts it. The failure happens at the panel level: the panel can't execute the compound command, resulting in the 60s polling timeout followed by `error_protom_session`.

Three distinct failure modes:
1. **Unknown command** (e.g. `TEST`): Instant GraphQL validation error (`BAD_USER_INPUT` with no `"data"` key in response), raises `SecuritasDirectError(http_status=400)` → marked unsupported, fallback triggers
2. **Application-level rejection** (e.g. `ARMINTEXT1` on Italian panel, `DARM1DARMPERI` on Spanish panel): Returns `"errors"` with `"data": {"res": "ERROR"}` or `"data": {"status": 404}`, raises `SecuritasDirectError(http_status=404)` → marked unsupported, fallback triggers
3. **Valid-but-unsupported command** (e.g. `DARM1DARMPERI` on a panel that accepts but can't execute it): Accepted by API, 60s polling, `error_protom_session` / `TECHNICAL_ERROR` → raises `SecuritasDirectError` (no `http_status`) → re-raised immediately, NOT marked unsupported (transient)

## Log Evidence

Captured 2026-03-06. Full sequence: ARM (E) → DISARM with DARM1DARMPERI → 60s WAIT polling → error_protom_session → CheckAlarmStatus confirms D (disarmed).
