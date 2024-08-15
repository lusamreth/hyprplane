import asyncio
import json
import socket
from enum import Enum
from queue import Queue
from threading import Thread
from typing import Callable, Dict, List

from hyprplane.ipc import getEventStreamPath


class WindowEvent(Enum):
    WORKSPACE_NAME = "workspace"
    WORKSPACE_V2 = "workspacev2"
    FOCUSED_MON = "focusedmon"
    ACTIVE_WINDOW = "activewindow"
    ACTIVE_WINDOW_V2 = "activewindowv2"
    FULLSCREEN = "fullscreen"
    MONITOR_REMOVED = "monitorremoved"
    MONITOR_ADDED = "monitoradded"
    MONITOR_ADDED_V2 = "monitoraddedv2"
    CREATE_WORKSPACE = "createworkspace"
    CREATE_WORKSPACE_V2 = "createworkspacev2"
    DESTROY_WORKSPACE = "destroyworkspace"
    DESTROY_WORKSPACE_V2 = "destroyworkspacev2"
    MOVE_WORKSPACE = "moveworkspace"
    MOVE_WORKSPACE_V2 = "moveworkspacev2"
    RENAME_WORKSPACE = "renameworkspace"
    ACTIVE_SPECIAL = "activespecial"
    ACTIVE_LAYOUT = "activelayout"
    OPEN_WINDOW = "openwindow"
    CLOSE_WINDOW = "closewindow"
    MOVE_WINDOW = "movewindow"
    MOVE_WINDOW_V2 = "movewindowv2"
    OPEN_LAYER = "openlayer"
    CLOSE_LAYER = "closelayer"
    SUBMAP = "submap"
    CHANGE_FLOATING_MODE = "changefloatingmode"
    URGENT = "urgent"
    MINIMIZE = "minimize"
    SCREENCAST = "screencast"
    WINDOW_TITLE = "windowtitle"
    WINDOW_TITLE_V2 = "windowtitlev2"
    TOGGLE_GROUP = "togglegroup"
    MOVE_INTO_GROUP = "moveintogroup"
    MOVE_OUT_OF_GROUP = "moveoutofgroup"
    IGNORE_GROUP_LOCK = "ignoregrouplock"
    LOCK_GROUPS = "lockgroups"
    CONFIG_RELOADED = "configreloaded"
    EMPTY_PIN = "emptypin"

    def str(self):
        return self.value


# primitive based on https://wiki.hyprland.org/IPC/
class HyprlandEventHandler:
    def __init__(self):
        self.subscribers: Dict[str, list[Callable]] = {}
        self.event_stream_path = getEventStreamPath()
        self.loop = None
        self.msg_queue = Queue()
        self.running = False

    def start(self):
        """Start the event handler in a new thread."""
        self.running = True
        Thread(target=self._run_event_loop, daemon=True).start()
        # Thread(target=self._run_executor_loop).start()

    def _run_event_loop(self):
        print("Running event thread")
        self.running = True
        """Run the asyncio event loop in the new thread."""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self.read_events())

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
        while self.running and self.loop is not None:
            try:
                data = await self.loop.sock_recv(sock, 4096)
                if not data:
                    print("Connection closed. Reconnecting...")
                    sock.close()
                    sock = await self.connect_to_socket()
                    continue

                events = data.decode().strip().split("\n")

                for event in events:
                    self.msg_queue.put_nowait(event)

            except Exception as e:
                print(f"Error reading from socket: {e}")
                sock.close()
                sock = await self.connect_to_socket()

    async def process_event(self, event_string: str):
        try:
            event_type, event_data = list(
                map(lambda x: x.strip(), event_string.split(">>", 1))
            )[:2]

            # print(f"Received event: {event_type} ")
            # print(f"Event data: {event_data}")
            # print("EPO", event_type, self.subscribers.get(event_type))

            if not WindowEvent._value2member_map_[event_type]:
                print("not recognized")
                pass

            if self.subscribers.get(event_type):
                for callback in self.subscribers[event_type]:
                    await callback(event_data)

        except Exception as e:
            print(f"Error processing event: {e}")

    def subscribe(self, event_type: str, callback: Callable):
        if event_type not in self.subscribers:
            self.subscribers[event_type] = []

        self.subscribers[event_type].append(callback)

    async def publish(self, event_type: str, event_data: dict):
        if event_type in self.subscribers:
            events = self.subscribers[event_type]
            for callback in events:
                await callback(event_data)

    def stop(self):
        """Stop the event handler."""
        self.running = False
        if self.loop:
            self.loop.call_soon_threadsafe(self.loop.stop)


class Subscriber:
    def __init__(self, callback) -> None:
        self.callback = callback

    async def recieveMsg(self, msg):
        return await self.callback(msg)


async def main():
    event_handler = HyprlandEventHandler()

    # Example subscriber functions
    async def window_open_handler(data):
        print(f"-------------  Window open: {data} ---------")

    async def window_close_handler(data):
        print(f"-------------  Window closed: {data} ---------")

    # Subscribe to events
    event_handler.subscribe("openwindow", window_open_handler)
    event_handler.subscribe("closewindow", window_close_handler)

    # Start reading events
    await event_handler.read_events()


if __name__ == "__main__":
    asyncio.run(main())
