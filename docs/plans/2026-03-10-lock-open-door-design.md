# Smart Lock "Open Door" Feature

Issue: #313

## Problem

Securitas Danalock smart locks can be configured with latch hold-back (`holdBackLatchTime > 0`). When so configured, the `xSChangeSmartlockMode` mutation with `lock: false` unlatches the door (physically retracts the latch for `holdBackLatchTime` seconds) rather than simply unlocking it. After the latch releases, the lock settles into an unlocked state.

The user cannot unlatch the door again from Home Assistant because the lock already shows as "unlocked" and no "Open" action is available.

There is no separate API mutation for opening the door -- `{lock: false}` is the only command, and it both unlocks and unlatches.

## Design

Conditionally advertise `LockEntityFeature.OPEN` based on Danalock config:

- `holdBackLatchTime > 0`: set `OPEN` feature flag, add `async_open()` method
- `holdBackLatchTime == 0` or config unavailable: no `OPEN` flag, standard lock/unlock only

### State flow (unlatch-mode locks)

```
Locked   --{lock:false}-->  Unlatching (3s)  -->  Unlocked
Unlocked --{lock:false}-->  Unlatching (3s)  -->  Unlocked
Unlocked --{lock:true}--->  Locking          -->  Locked
```

### UI buttons

| State    | Buttons (unlatch mode)      | Notes                                    |
|----------|-----------------------------|------------------------------------------|
| Locked   | Lock, Unlock, Open          | Unlock and Open both send `{lock: false}` |
| Unlocked | Lock, Unlock, Open          | Open sends `{lock: false}` (unlatches)   |

For simple-unlock locks (`holdBackLatchTime == 0`), only Lock/Unlock are shown.

The Unlock button cannot be hidden when locked -- HA's `supported_features` is a static flag set. The redundancy when locked is harmless since both actions do the same thing.

## Changes

### `lock.py` (entity)

- `supported_features`: return `LockEntityFeature.OPEN` when `_danalock_config.features.holdBackLatchTime > 0`
- Add `async_open()`: calls `change_lock_mode(lock=False)`, same error handling as `async_unlock()`
- After lazy Danalock config fetch, call `async_write_ha_state()` so HA picks up the new feature flag

### No changes needed

- `hub.py`: `change_lock_mode(lock=False)` already exists
- `apimanager.py`: no new GraphQL mutation required
- `graphql_queries.py`: no new queries

### Tests

- `supported_features` returns `OPEN` when `holdBackLatchTime > 0`
- `supported_features` returns `0` when `holdBackLatchTime == 0` or config is None
- `async_open()` calls `change_lock_mode(lock=False)`
- `async_open()` error handling reverts state
