import asyncio
import json
import socket
from enum import Enum
from queue import Queue
from threading import Thread
from typing import Dict, List, Optional

from hyprplane.controller.layout import LayoutController
from hyprplane.controller.window import WindowController
from hyprplane.utils import hyprctlCommand


class EventType(Enum):
    WINDOW_OPEN = "openwindow"
    WINDOW_CLOSE = "closewindow"
    WORKSPACE_CHANGED = "workspace"


class LayoutMode(Enum):
    TILED = 1
    STAGE_MANAGER = 2


class WindowGroup:
    def __init__(self, mainWindow: Dict, sideWindows: List[Dict]):
        self.mainWindow = mainWindow
        self.sideWindows = sideWindows


class StageController(LayoutController):
    def __init__(self, windCont: WindowController):
        super().__init__(windCont)
        self.currentMode: LayoutMode = LayoutMode.TILED
        self.currentWorkspaceId: Optional[int] = None
        self.windowGroups: List[WindowGroup] = []
        self.activeGroupIndex: int = 0
        self.event_queue = Queue()
        self.event_handler = HyprlandEventHandler(self)

    async def start(self):
        # Start event handling in a separate thread
        Thread(target=self.event_handler.start, daemon=True).start()
        # Start processing events from the queue
        asyncio.create_task(self.process_events())
        # Start periodic layout updates
        asyncio.create_task(self.periodic_layout_update())

    async def process_events(self):
        while True:
            while not self.event_queue.empty():
                event_type, event_data = self.event_queue.get()
                await self.handle_event(event_type, event_data)
            await asyncio.sleep(0.1)  # Small delay to prevent busy-waiting

    async def periodic_layout_update(self):
        while True:
            if self.currentMode == LayoutMode.STAGE_MANAGER:
                await self.update_layout()
            await asyncio.sleep(1)  # Update every second

    async def update_layout(self):
        clients = await self.getWorkspaceClients()
        current_addresses = set(client["address"] for client in clients)
        staged_addresses = set(
            group.mainWindow["address"] for group in self.windowGroups
        )
        staged_addresses.update(
            window["address"]
            for group in self.windowGroups
            for window in group.sideWindows
        )

        # Add new windows
        for client in clients:
            if client["address"] not in staged_addresses:
                await self.add_window_to_stage(client["address"])

        # Remove closed windows
        for group in self.windowGroups[:]:
            if group.mainWindow["address"] not in current_addresses:
                await self.remove_window_from_stage(group.mainWindow["address"])
            group.sideWindows = [
                w for w in group.sideWindows if w["address"] in current_addresses
            ]

        await self.applyStageManagerLayout()

    async def handle_event(self, event_type: EventType, event_data: dict):
        if self.currentMode != LayoutMode.STAGE_MANAGER:
            return

        if event_type == EventType.WINDOW_OPEN:
            window_address = event_data.get("window")
            workspace_id = event_data.get("workspace")
            if workspace_id == self.currentWorkspaceId:
                await self.add_window_to_stage(window_address)
        elif event_type == EventType.WINDOW_CLOSE:
            window_address = event_data.get("window")
            await self.remove_window_from_stage(window_address)
        elif event_type == EventType.WORKSPACE_CHANGED:
            # Handle workspace change if needed
            pass

    async def add_window_to_stage(self, window_address: str):
        await hyprctlCommand(f"dispatch togglefloating address:{window_address}")
        new_window = await self.wController.getWindow(window_address)
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

    async def remove_window_from_stage(self, window_address: str):
        for i, group in enumerate(self.windowGroups):
            if group.mainWindow["address"] == window_address:
                if group.sideWindows:
                    group.mainWindow = group.sideWindows.pop(0)
                else:
                    self.windowGroups.pop(i)
                break
            elif window_address in [w["address"] for w in group.sideWindows]:
                group.sideWindows = [
                    w for w in group.sideWindows if w["address"] != window_address
                ]
                break
        await self.applyStageManagerLayout()

    # ... (rest of the StageController methods)


class HyprlandEventHandler:
    def __init__(self, stage_controller: StageController):
        self.stage_controller = stage_controller
        self.event_stream_path = "/tmp/hypr/$HYPRLAND_INSTANCE_SIGNATURE/.socket2.sock"

    def start(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self.read_events())

    async def connect_to_socket(self):
        while True:
            try:
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                sock.connect(self.event_stream_path)
                return sock
            except (FileNotFoundError, ConnectionRefusedError):
                print(
                    f"Socket not found at {self.event_stream_path}. Retrying in 5 seconds..."
                )
                await asyncio.sleep(5)

    async def read_events(self):
        sock = await self.connect_to_socket()
        sock.setblocking(False)

        while True:
            try:
                data = await asyncio.get_event_loop().sock_recv(sock, 4096)
                if not data:
                    print("Connection closed. Reconnecting...")
                    sock.close()
                    sock = await self.connect_to_socket()
                    continue

                events = data.decode().strip().split("\n")
                for event in events:
                    await self.process_event(event)
            except Exception as e:
                print(f"Error reading from socket: {e}")
                sock.close()
                sock = await self.connect_to_socket()

    async def process_event(self, event_string: str):
        try:
            event_type, event_data = event_string.split(">>", 1)
            event_type = event_type.strip()
            event_data = json.loads(event_data.strip())

            print(f"Received event: {event_type}")
            print(f"Event data: {event_data}")

            try:
                enum_event_type = EventType(event_type)
                self.stage_controller.event_queue.put((enum_event_type, event_data))
            except ValueError:
                # Event type not in our EventType enum, ignore it
                pass
        except Exception as e:
            print(f"Error processing event: {e}")


async def startController():
    sysLogger.debug("starting controller...")
    windowstack = WindowStack()
    windCont = WindowController()
    layoutCont = StageController(windCont)

    # Start the StageController
    await layoutCont.start()

    cont = buildController(windowstack, windCont, layoutCont)
    server = await asyncio.start_unix_server(cont, SOCKET_PATH)

    async with server:
        sysLogger.debug("server stacking", server)
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(startController())
