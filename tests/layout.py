import asyncio
import concurrent.futures
import os
import subprocess
import threading
import unittest

from hyprplane.commander import EnterStage
from hyprplane.controller.stage_manager import StageController
from hyprplane.controller.window import WindowController, WindowStack
from hyprplane.utils import hyprctl_cmd

TEST_SAMPLE_WINDOS = 4


async def window_spawner(wid):
    await hyprctl_cmd(f"dispatch workspace {wid}")

    for _ in range(0, TEST_SAMPLE_WINDOS):
        status = subprocess.Popen(["kitty"])
        print("KITTY STATUS: ", status)


async def window_cleanup(wid):
    await asyncio.sleep(1)
    target_clients = await get_workspace_clients(wid)
    print("CLEANING UP WINDOWS:", len(target_clients))
    for wc in target_clients:
        print(wc)
        addr = wc["address"]
        class_name = wc["class"]
        if class_name == "kitty":
            await hyprctl_cmd(f"dispatch closewindow address:{addr}")


async def get_workspace_clients(wid: int):
    workspace_id = wid
    origin_clients = await hyprctl_cmd("clients", getOutput=True)
    target_clients = []
    for client in origin_clients:
        if client["workspace"]["id"] == workspace_id:
            target_clients.append(client)
    return target_clients


class AioTestCase(unittest.TestCase):

    # noinspection PyPep8Naming
    def __init__(self, methodName="runTest", loop=None):
        self.loop = loop or asyncio.get_event_loop()
        self._function_cache = {}
        super(AioTestCase, self).__init__(methodName=methodName)

    def coroutine_function_decorator(self, func):
        def wrapper(*args, **kw):
            return self.loop.run_until_complete(func(*args, **kw))

        return wrapper

    def __getattribute__(self, item):
        attr = object.__getattribute__(self, item)
        if asyncio.iscoroutinefunction(attr):
            if item not in self._function_cache:
                self._function_cache[item] = self.coroutine_function_decorator(attr)
            return self._function_cache[item]
        return attr

    def run_in_thread(self, target, *args):
        """Run a blocking function in a separate thread."""
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = self.loop.run_in_executor(executor, target, *args)
            return self.loop.run_until_complete(future)


class TestLayoutGrid(AioTestCase):
    # def __init__(self, methodName: str = "runTest") -> None:
    #     self.testing_workspace: int = 4
    #     super().__init__()
    #     pass

    async def setUp(self):
        """Set up the test environment."""
        # Set up your testing workspace or any other necessary preparations.
        self.testing_workspace = 4

        # Start the _run_executor_loop in the background immediately.
        wind_controller = WindowController()
        self.stage_controller = StageController(wind_controller)

        # Start the executor loop immediately in a background thread
        # await self.stage_controller.start()

        self.exec_thread = threading.Thread(
            target=self.stage_controller._run_executor_loop, daemon=False
        )

        # # Start the window event loop in a separate thread
        # self.stage_controller.hyprland_event

        # fix this stupid event handling error on thread not running to
        # completion , the system suppose to run forever until the kill signal
        # is sent

        # self.event_thread = threading.Thread(
        #     target=self.stage_controller.hyprland_event._run_event_loop, daemon=False
        # )

        # self.event_thread.start()
        self.exec_thread.start()

    async def tearDown(self):
        """Clean up after the test."""
        # Stop the stage controller and clean up resources.
        self.stage_controller.stop()
        self.stage_controller.hyprland_event.running = False

        await window_cleanup(self.testing_workspace)

        # Ensure the thread has stopped
        self.exec_thread.join(timeout=1)
        self.event_thread.join(timeout=1)

        if self.exec_thread.is_alive():
            print("Thread did not exit as expected")

    async def test_stage_grid_layout(self):
        target_clients = await get_workspace_clients(self.testing_workspace)
        if len(target_clients) > 0:
            print(
                "Cannot run test! Make sure that all your windows are moved or deleted first"
            )
            os._exit(1)

        await window_spawner(self.testing_workspace)
        await asyncio.sleep(1)

        stage_strategy = EnterStage()

        wind_stack = WindowStack()

        await stage_strategy.execute(self.stage_controller, wind_stack, [""])

        await asyncio.sleep(1)
        sampled_group = self.stage_controller.window_groups[self.testing_workspace][0]

        addr = sampled_group.side_windows[1]["address"]
        await hyprctl_cmd(f"dispatch closewindow address:{addr}")

        # Ensure we wait enough time for the operations to complete
        await asyncio.sleep(4)


if __name__ == "__main__":
    unittest.main()
