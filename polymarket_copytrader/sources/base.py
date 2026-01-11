from __future__ import annotations

import abc
from typing import Any, AsyncIterator


class ActivitySource(abc.ABC):
    @abc.abstractmethod
    async def events(self) -> AsyncIterator[dict[str, Any]]:
        raise NotImplementedError
