"""Activity domain: panel timeline (xSActV2)."""

from __future__ import annotations

from ..graphql_queries import ACTIVITY_QUERY
from ..models import ActivityEvent, Installation
from ..responses import ActivityEnvelope
from ._base import _ClientBase


class _ActivityMixin(_ClientBase):
    """Panel-activity timeline fetch."""

    async def get_activity(
        self,
        installation: Installation,
        *,
        num_rows: int = 30,
        offset: int = 0,
        time_filter: str = "LASTMONTH",
    ) -> list[ActivityEvent]:
        """Fetch entries from the alarm panel's activity timeline (xSActV2)."""
        content = {
            "operationName": "ActV2Timeline",
            "variables": {
                "numinst": installation.number,
                "panel": installation.panel,
                "numRows": num_rows,
                "offset": offset,
                "timeFilter": time_filter,
            },
            "query": ACTIVITY_QUERY,
        }
        envelope = await self._execute_graphql(
            content,
            "ActV2Timeline",
            ActivityEnvelope,
            installation=installation,
        )
        return envelope.data.xSActV2.reg or []
