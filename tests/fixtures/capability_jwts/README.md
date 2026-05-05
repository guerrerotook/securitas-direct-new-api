Real-world capability JWT bodies captured from `xSSrv` GraphQL responses, decoded
and scrubbed. Each fixture covers a distinct installation shape that the
multi-system alarm panel work must handle.

Scrubbed:
- `ins` (numinst) replaced with `INST_<placeholder>`
- `exp` / `iat` set to fixed reference timestamps
- `element` / `nova` (opaque encrypted blobs) omitted

Kept:
- `installations[].role`
- `installations[].cap` (the only field this work cares about)
- `alarm_partitions` from `configRepoUser.alarmPartitions` when present
- `services_relevant` — subset of services attributes used by `_detect_peri`

Use in tests: `mock_graphql.make_jwt(installations=fixture["decoded_jwt_body"]["installations"])`
to construct a JWT from the fixture data. Signature is not validated by
production code (`verify_signature: false`), so any signing key works.

| Fixture | Panel | Country | Scenario |
|---|---|---|---|
| `vatrinus_uk_annex.json` | SDVFAST | UK | Has annex (`ARMANNEX`/`DARMANNEX` in caps) |
| `italy_partial_only.json` | SDVECU | IT | Partial-only (`ARMNIGHT` only, no `ARMDAY`); peri via `alarmPartitions` not via JWT |
| `spain_full_peri.json` | SDVFAST | ES | Full feature set (`ARMDAY`+`ARMNIGHT`) with `PERI` |
| `spain_full_no_peri.json` | SDVFAST | ES | Full feature set (`ARMDAY`+`ARMNIGHT`), no `PERI` |
