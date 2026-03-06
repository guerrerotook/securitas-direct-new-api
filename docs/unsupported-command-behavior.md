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

This bug is now fixed. After `_poll_operation` returns, `arm_alarm()` and `disarm_alarm()` in `apimanager.py` check for `res: "ERROR"` with a non-`NON_BLOCKING` error type (e.g. `TECHNICAL_ERROR`). When detected, they raise `SecuritasDirectError`, which triggers the `CommandResolver`'s fallback chain in `_execute_step()`. The failed command is marked unsupported via `resolver.mark_unsupported()` and skipped in future resolutions.

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

Two distinct failure modes:
1. **Unknown command** (e.g. `TEST`): Instant GraphQL validation error (`BAD_USER_INPUT`), raises `SecuritasDirectError` → fallback triggers correctly
2. **Valid-but-unsupported command** (e.g. `DARM1DARMPERI` on a panel that doesn't support it): Accepted by API, 60s polling, `error_protom_session` / `TECHNICAL_ERROR` → now raises `SecuritasDirectError`, fallback triggers correctly

## Log Evidence

Captured 2026-03-06. Full sequence: ARM (E) → DISARM with DARM1DARMPERI → 60s WAIT polling → error_protom_session → CheckAlarmStatus confirms D (disarmed).
