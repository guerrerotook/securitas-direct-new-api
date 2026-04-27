"""Shared Pydantic utilities for the Securitas Direct API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, model_validator


class NullSafeBase(BaseModel):
    """Base that coerces None to '' for any str field with a default.

    The Securitas API returns null for many string fields during polling
    or when fields are not applicable.  Pydantic rejects None for str
    fields even with a default.  This base class coerces None -> "" for
    all str-typed fields before validation.
    """

    @model_validator(mode="before")
    @classmethod
    def _coerce_null_strings(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        # Copy to avoid mutating the caller's dict
        needs_copy = False
        for name, field_info in cls.model_fields.items():
            keys = [name]
            if field_info.validation_alias and isinstance(
                field_info.validation_alias, str
            ):
                keys.append(field_info.validation_alias)
            for key in keys:
                if key in data and data[key] is None and field_info.annotation is str:
                    if not needs_copy:
                        data = dict(data)
                        needs_copy = True
                    data[key] = ""
        return data
