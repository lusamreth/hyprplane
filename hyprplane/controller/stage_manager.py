import asyncio
import concurrent
import queue
import random
import threading
from collections import deque
from enum import Enum
from queue import Queue
from subprocess import Popen
from threading import Thread
from typing import Dict, List, Optional, Tuple

from hyprplane.controller.layout import LayoutController
from hyprplane.controller.window import WindowController
from hyprplane.drawer import printWindowLayout
from hyprplane.event import HyprlandEventHandler

from ..utils import hyprctlCommand


class LayoutMode(Enum):
    TILED = 1
    STAGE_MANAGER = 2


class WindowGroup:
    def __init__(self, mainWindow: Dict, sideWindows: List[Dict]):
        self.mainWindow = mainWindow
        self.sideWindows = sideWindows


class StageController(LayoutController):
    def __init__(self, windCont: WindowController) -> None:
        super().__init__(windCont)
        self.hyprlandEvent = HyprlandEventHandler()
        self.currentMode: Dict[int, LayoutMode] = {}
        self.currentWorkspaceId: Optional[int] = None
        self.windowGroups: List[WindowGroup] = []
        self.activeGroupIndex: int = 0
        self.window_open_queue = deque(maxlen=5)  # Store last 5 window open events
        self.event = threading.Event()
        self.prevPos = []
        self.is_processing = False
        self.last_window_open_time = 0

    def setEvent(self, event: threading.Event):
        pass
        # self.event = event

    async def start(self):
        # await self.eventServer()
        # threading.Thread(target=self._run_executor_loop).run()
        self.hyprlandEvent.subscribe("openwindow", self.run)
        self.hyprlandEvent.start()

    def _run_executor_loop(self):
        """Run the asyncio event loop in the new thread."""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self.eventHandler())

    async def eventHandler(self):
        while True:
            try:
                # Use get_nowait() for non-blocking operation
                event = self.hyprlandEvent.msgQueue.get_nowait()
            except queue.Empty:
                # If queue is empty, wait a bit before trying again
                await asyncio.sleep(0.1)
                continue

            et, ed = event.split(">>")

            if et == "openwindow":
                self.debounce_time = 0.1
                current_time = asyncio.get_event_loop().time()
                if current_time - self.last_window_open_time > self.debounce_time:
                    self.last_window_open_time = current_time
                    await self.handle_window_open()
                # self.window_open_queue.append(asyncio.get_event_loop().time())
                # if not self.is_processing:
                #     asyncio.create_task(self.process_window_opens())

    async def handle_window_open(self):
        initial_pos_count = len(self.prevPos)
        self.max_retries = 5
        for attempt in range(self.max_retries):
            await self.enterStageManagerMode()
            if len(self.prevPos) != initial_pos_count:
                return  # Success

            if attempt < self.max_retries - 1:
                await asyncio.sleep(1)  # Short delay between retries

        print("Failed to update window positions after retries")

    async def process_window_opens(self):
        self.is_processing = True
        try:
            while self.window_open_queue:
                # Wait for a short time to see if more windows open
                await asyncio.sleep(0.1)

                # Process all window opens that happened in this batch
                while (
                    self.window_open_queue
                    and self.window_open_queue[0]
                    <= asyncio.get_event_loop().time() - 0.1
                ):
                    self.window_open_queue.popleft()

                # Only enter stage manager mode if there were actually window opens
                if not self.window_open_queue:
                    initial_pos_count = len(self.prevPos)
                    await self.enterStageManagerMode()
                    if len(self.prevPos) == initial_pos_count:
                        print(
                            "Stage manager mode did not update window positions as expected"
                        )
                        retry_count = 0
                        max_retries = 5
                        while (
                            len(self.prevPos) == initial_pos_count
                            and retry_count < max_retries
                        ):
                            print(
                                f"Attempting recovery - Retry {retry_count + 1}/{max_retries}"
                            )
                            await asyncio.sleep(1)  # Wait a bit before retrying
                            await self.enterStageManagerMode()
                            retry_count += 1
                        # Here you might want to add some recovery logic
        finally:
            self.is_processing = False

    async def setCurrentWorkspaceMode(self, mode: LayoutMode):
        win = await self.wController.getActiveWindow()
        if win is None:
            return
        wid = win["workspace"]["id"]
        print("WWIN",win["address"],wid)
        self.currentWorkspaceId = wid
        self.currentMode[wid] = mode

    async def getCurrentWorkspaceMode(self):
        win = await self.wController.getActiveWindow()
        defaultMode = LayoutMode.TILED
        if win is None:
            return defaultMode

        wid = win["workspace"]["id"]
        self.currentWorkspaceId = wid
        res = self.currentMode.get(wid)
        print("M",res)
        if res is None:
            await self.setCurrentWorkspaceMode(defaultMode)
        else:
            return res

        return defaultMode

    async def toggleLayoutMode(self):
        currMode = await self.getCurrentWorkspaceMode()
        print("MODE",currMode)
        if currMode == LayoutMode.TILED:
            # Popen(["hyprpm", "enable", "hyprbars"])
            await self.enterStageManagerMode()
        elif currMode == LayoutMode.STAGE_MANAGER:
            # Popen(["hyprpm", "disable", "hyprbars"])
            await self.exitStageManagerMode()

    async def loadWindowGroup(self):
        clients = await self.getWorkspaceClients()
        if not clients:
            return

        self.windowGroups = self.createWindowGroups(clients)

    async def enterStageManagerMode(self):
        await self.setCurrentWorkspaceMode(LayoutMode.STAGE_MANAGER)
        await self.loadWindowGroup()
        await self.applyStageManagerLayout()

    async def run(self, event_data):

        self.event.wait()
        dataArray = event_data.split(",")
        addrs = dataArray[0].strip()
        currMode = await self.getCurrentWorkspaceMode()

        if currMode == LayoutMode.STAGE_MANAGER:
            res = await hyprctlCommand(f"dispatch setfloating address:{addrs}", True)
            await self.loadWindowGroup()
            # await self.add_window_to_stage(event_data)
            # self.currentMode = LayoutMode.STAGE_MANAGER
            await self.enterStageManagerMode()

        self.event.clear()

    async def add_window_to_stage(self, window_address: str):
        await hyprctlCommand(f"dispatch togglefloating address:{window_address}")
        new_window = await self.wController.getWinFromGroup.getWindow(window_address)

        if new_window:
            if not self.windowGroups:
                self.windowGroups.append(WindowGroup(new_window, []))
            else:
                last_group = self.windowGroups[-1]
                if len(last_group.sideWindows) < 2:
                    last_group.sideWindows.append(new_window)
                else:
                    self.windowGroups.append(WindowGroup(new_window, []))
            await self.applyStageManagerLayout()

    async def eventServer(self):
        self.hyprlandEvent.subscribe("openwindow", self.run)
        # await self.hyprlandEvent.read_events()

    def createWindowGroups(self, clients: List[Dict]) -> List[WindowGroup]:
        groups = []
        miniWindowChunks = 10

        # Create groups of up to 3 windows
        for i in range(0, len(clients), miniWindowChunks):
            group_clients = clients[i : i + miniWindowChunks]
            groups.append(WindowGroup(group_clients[0], group_clients[1:]))

        return groups

    async def exitStageManagerMode(self):
        for group in self.windowGroups:
            for window in [group.mainWindow] + group.sideWindows:
                await hyprctlCommand(
                    f"dispatch settiled address:{window['address']}", True
                )

        await self.setCurrentWorkspaceMode(LayoutMode.TILED)
        self.windowGroups = []

    async def handleWindowChange(self, event_type):
        currTS = asyncio.get_event_loop().time()
        print("CCU,cu", currTS)
        update_interval = 0.1
        if currTS - self.last_window_open_time < update_interval:
            return  # Debounce: skip if too soon after last update

        if event_type == "openwindow":
            self.current_windows.add(event_data)
        elif event_type == "closewindow":
            self.current_windows.discard(event_data)
        pass

    async def applyStageManagerLayout(self):
        if not self.windowGroups:
            return
        print("---- APPLIED ------", len(self.windowGroups[0].sideWindows))

        await self.loadWindowGroup()
        screenWidth, screenHeight, offsetX, offsetY = await self.getScreenSize()

        # Main window dimensions (larger and positioned to the right)
        mainWidth = int(screenWidth * 0.8)
        mainHeight = int(screenHeight * 0.9)
        mainX = offsetX + (screenWidth - mainWidth) - 20  # 20px padding from right edge
        mainY = offsetY + (screenHeight - mainHeight) // 2
        # Minified window dimensions (smaller and to the left)
        miniWidth = int(screenWidth * 0.18)
        miniHeight = int(screenHeight * 0.24)
        miniX = offsetX + 0  # 20px padding from left edge
        miniY = offsetY + 0  # 20px padding from top edge
        miniVerticalGap = 30  # Gap between minified windows
        miniHorizontalGap = 30  # Gap between columns when overflow occurs

        clients = await self.getWorkspaceClients()
        await self.toggleFloatingWorkspace(clients)

        # Position the active group's main window
        activeGroup = self.windowGroups[self.activeGroupIndex]
        await self.moveAndResizeWindow(
            activeGroup.mainWindow["address"], mainX, mainY, mainWidth, mainHeight
        )

        # Position minified windows for all groups in a vertical stack
        miniWindows = []
        for i, group in enumerate(self.windowGroups):
            if i != self.activeGroupIndex:
                miniWindows.append(group.mainWindow)
            miniWindows.extend(group.sideWindows)

        maxWindowsPerColumn = (screenHeight - miniY) // (miniHeight + miniVerticalGap)

        self.prevPos = []

        for i, window in enumerate(miniWindows):
            column = i // maxWindowsPerColumn
            row = i % maxWindowsPerColumn

            xPosition = miniX + column * (miniWidth + miniHorizontalGap)
            yPosition = miniY + row * (miniHeight + miniVerticalGap)
            self.prevPos.append(
                {"x": xPosition, "y": yPosition, "w": miniWidth, "h": miniHeight}
            )
            await self.moveAndResizeWindow(
                window["address"], xPosition, yPosition, miniWidth, miniHeight
            )

        # Raise the active window to the top
        await hyprctlCommand(
            f"dispatch movetoTop address:{activeGroup.mainWindow['address']}"
        )

    async def cycleMainWindow(self):
        if self.currentMode != LayoutMode.STAGE_MANAGER or not self.windowGroups:
            return

        activeGroup = self.windowGroups[self.activeGroupIndex]
        allWindows = [activeGroup.mainWindow] + activeGroup.sideWindows
        newMain = allWindows.pop(0)
        allWindows.append(newMain)
        newActive = WindowGroup(allWindows[0], allWindows[1:])
        self.windowGroups[self.activeGroupIndex] = newActive
        await self.focusWindow(newActive.mainWindow["address"])
        await self.applyStageManagerLayout()

    async def getWorkspaceClients(self) -> List[Dict]:
        activeWindow = await self.wController.getActiveWindow()
        if activeWindow is None:
            return []

        self.currentWorkspaceId = activeWindow["workspace"]["id"]
        cl = self.wController.props.get("clients")

        if cl is None:
            return []

        clients = await cl.fetch()

        if clients is None:
            return []

        return [
            client
            for client in clients
            if client["workspace"]["id"] == self.currentWorkspaceId
        ]
