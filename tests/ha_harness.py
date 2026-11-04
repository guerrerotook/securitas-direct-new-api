"""One import path for the HA test helpers, on old and new HA."""

try:
    from pytest_homeassistant.common import (
        MockConfigEntry,
        async_fire_time_changed,
    )
except ImportError:
    from pytest_homeassistant_custom_component.common import (
        MockConfigEntry,
        async_fire_time_changed,
    )

__all__ = ["MockConfigEntry", "async_fire_time_changed"]
