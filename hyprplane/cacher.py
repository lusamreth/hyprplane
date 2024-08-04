import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from cachetools import TTLCache

from .utils import hyprctlCommand

MAX_POOL = 4
SHORT_LIVE_CACHE = 1
LONG_LIVE_CACHE = 600

executor = ThreadPoolExecutor(MAX_POOL)


class CacheControl(TTLCache):
    def __init__(self, coroutine_factory, retention=SHORT_LIVE_CACHE) -> None:
        self.coFactory = coroutine_factory
        self.ready = False
        self.event = asyncio.Event()
        super().__init__(maxsize=1024, ttl=retention)

    async def fetch(self):
        self.event.set()
        result: asyncio.Task | None = self.get("_STORE")
        if result is None:
            if self.coFactory is None:
                raise Exception("Must set coroutine factory before fetching data.")
            result = await self.coFactory()
        else:
            # print("no cache hit", result)
            return result

        self.__setitem__("_STORE", result)
        return result


@dataclass
class HyprlandTask:
    pid: str
    command: str
    args: list[str]
    flags: list[str]
    outputCapture: bool
    retention: float | None

    @classmethod
    def create(cls, command, args=[], flags=[], output=False) -> "HyprlandTask":
        return cls(
            pid="",
            command=command,
            outputCapture=output,
            retention=None,
            args=args,
            flags=flags,
        )

    def asTask(self):
        return lambda: hyprctlCommand(self.command, self.outputCapture)

    async def run(self):
        return await hyprctlCommand(self.command, self.outputCapture)


class BackgroundRefresher:
    def __init__(self) -> None:
        self.refreshRate = 1
        # self.task =
        pass

    pass


def hyprCommandBatchProcess(tasks: list[HyprlandTask]):
    gatheringTask = [hyprctlCommand(task.command, task.outputCapture) for task in tasks]
    loop = asyncio.get_event_loop()
    result = loop.run_until_complete(asyncio.gather(*gatheringTask))


if __name__ == "__main__":
    hyprCommandBatchProcess(
        [
            HyprlandTask.create("clients", True),
            HyprlandTask.create("monitors", True),
        ]
    )
    pass
