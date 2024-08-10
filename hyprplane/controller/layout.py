import random
from typing import Dict, List, Optional, Tuple

from hyprplane.controller.window import WindowController
from hyprplane.drawer import printWindowLayout

from ..utils import hyprctl_cmd


class LayoutController(WindowController):
    def __init__(self, windCont: WindowController) -> None:
        super().__init__()
        self.is_floating = False
        self.window_control = windCont
        self.layout_history: Dict[int, List[Dict]] = {}
        self.current_workspace_id: Optional[int] = None

    # async def applyStageManagerLayout(self, clients: List[Dict]):
    #     screen_width, screen_height, offset_x, offset_y = await self.getScreenSize()
    #     num_clients = len(clients)
        
    #     if num_clients == 0:
    #         return
        
    #     # Main window dimensions
    #     main_width = int(screen_width * 0.75)
    #     main_height = int(screen_height * 0.85)
    #     main_x = offset_x + (screen_width - main_width) // 2
    #     main_y = offset_y + (screen_height - main_height) // 2
        
    #     # Side stack dimensions
    #     stack_width = int(screen_width * 0.2)
    #     stack_height = int(screen_height * 0.15)
    #     stack_x = offset_x + screen_width - stack_width - 20
    #     stack_y = offset_y + 20
    #     stack_spacing = 20
        
    #     # Apply layout
    #     for i, client in enumerate(clients):
    #         if i == 0:  # Main window
    #             await self.moveAndResizeWindow(client["address"], main_x, main_y, main_width, main_height)
    #             await self.focusWindow(client["address"])
    #             await hyprctlCommand("dispatch bringactivetotop")
    #         else:  # Stacked windows
    #             y_position = stack_y + (i - 1) * (stack_height + stack_spacing)
    #             await self.moveAndResizeWindow(client["address"], stack_x, y_position, stack_width, stack_height)

    async def updateLayoutHistory(self) -> None:
        if self.current_workspace_id is None:
            return

        cl = self.window_control.props.get("clients")
        if cl is None:
            return
        clients = await cl.fetch()
        if clients is None:
            return

        workspace_clients = [
            {
                "address": client["address"],
                "size": client["size"],
                "at": client["at"],
                "class": client["class"],
                "workspace": client["workspace"]["id"]
            }
            for client in clients
            if client["workspace"]["id"] == self.current_workspace_id
        ]
        self.layout_history[self.current_workspace_id] = workspace_clients

    async def validateLayoutHistory(self) -> bool:
        if self.current_workspace_id is None:
            return False

        cl = self.window_control.props.get("clients")
        if cl is None:
            return False
        current_clients = await cl.fetch()
        if current_clients is None:
            return False
        current_workspace_clients = [
            client for client in current_clients
            if client["workspace"]["id"] == self.current_workspace_id
        ]

        if self.current_workspace_id not in self.layout_history:
            return False

        stored_clients = self.layout_history[self.current_workspace_id]

        if len(current_workspace_clients) != len(stored_clients):
            return False

        for stored, current in zip(stored_clients, current_workspace_clients):
            if (stored["address"] != current["address"] or
                    stored["class"] != current["class"]):
                return False

        return True

    async def toggleFloatMode(self):
        active_window = await self.window_control.getActiveWindow()
        if active_window is None:
            return

        self.current_workspace_id = active_window["workspace"]["id"]
        clients = await self.window_control.getWindowWithinWorkspace(self.current_workspace_id)
        if clients is None:
            return


        if not self.is_floating:
            for client in clients:
                address = client["address"]
                res = await hyprctl_cmd(f"dispatch setfloating address:{address}", True)
                print("RRRRR ",res)
            # await self.applyFloatingLayout(clients)
        else:
            await self.updateLayoutHistory()
            await self.restoreWindowLayout(clients)
            print("IS FLOATINGGGGGGGGGGGGGGGGGGGGGGGGGG",self.layout_history)

            for client in clients:
                address = client["address"]
                await hyprctl_cmd(f"dispatch settiled address:{address}", True)
        
        await self.applyFloatingLayout(clients)
        # await self.toggleFloatingWorkspace(clients)

        self.is_floating = not self.is_floating

    async def applyFloatingLayout(self, clients: List[Dict]):
        num_clients = len(clients)
        if num_clients == 1:
            await self.floatSingleWindow(clients[0])
        elif num_clients == 2:
            await self.floatTwoWindows(clients)
        elif num_clients == 3:
            await self.floatThreeWindows(clients)
            # await self.applyStageManagerLayout(clients)
        elif num_clients == 4:
            await self.floatFourWindows(clients)
        elif num_clients == 5:
            await self.floatFiveWindows(clients)
        else:
            await self.floatSixOrMoreWindows(clients)
            # await self.applyStageManagerLayout(clients)

    async def floatSingleWindow(self, client):
        screen_width, screen_height, offset_x, offset_y,_ = await self.getScreenSize()
        window_width = int(screen_width * 0.6)
        window_height = int(screen_height * 0.6)
        x = offset_x + (screen_width - window_width) // 2
        y = offset_y + (screen_height - window_height) // 2
        await self.move_and_resize_window(client["address"], x, y, window_width, window_height)

    async def floatTwoWindows(self, clients):
        screen_width, screen_height, offset_x, offset_y,_ = await self.getScreenSize()
        window_width = int(screen_width * 0.5)
        window_height = int(screen_height * 0.5)
        overlap = int(window_width * 0.1)
        positions = [
            (offset_x + (screen_width - window_width) // 2, offset_y + (screen_height - window_height) // 2 - overlap),
            (offset_x + (screen_width - window_width) // 2, offset_y + (screen_height - window_height) // 2 + overlap),
        ]
        for client, (x, y) in zip(clients, positions):
            await self.move_and_resize_window(client["address"], x, y, window_width, window_height)

    async def floatThreeWindows(self, clients):
        screen_width, screen_height, offset_x, offset_y,_ = await self.getScreenSize()
        back_width = int(screen_width * 0.45)
        back_height = int(screen_height * 0.45)
        center_width = int(screen_width * 0.5)
        center_height = int(screen_height * 0.5)
        overlap = int(back_width * 0.1)
        positions = [
            (offset_x + (screen_width - back_width) // 2, offset_y + (screen_height - back_height) // 2 - overlap),
            (offset_x + (screen_width - back_width) // 2, offset_y + (screen_height - back_height) // 2 + overlap),
            (offset_x + (screen_width - center_width) // 2, offset_y + (screen_height - center_height) // 2),
        ]
        for client, (x, y) in zip(clients, positions):
            width, height = (back_width, back_height) if client != clients[2] else (center_width, center_height)
            print("Waa Haa",width,height)
            await self.move_and_resize_window(client["address"], x, y, width, height)

    async def floatFourWindows(self, clients):
        screen_width, screen_height, offset_x, offset_y,_ = await self.getScreenSize()
        window_width = int(screen_width * 0.45)
        window_height = int(screen_height * 0.45)
        overlap = int(window_width * 0.1)
        base_positions = [
            (offset_x, offset_y),
            (offset_x + screen_width - window_width, offset_y),
            (offset_x, offset_y + screen_height - window_height),
            (offset_x + screen_width - window_width, offset_y + screen_height - window_height),
        ]
        positions = [(x + random.randint(-overlap, overlap), y + random.randint(-overlap, overlap)) for x, y in base_positions]
        for client, (x, y) in zip(clients, positions):
            await self.move_and_resize_window(client["address"], x, y, window_width, window_height)

    async def floatFiveWindows(self, clients):
        screen_width, screen_height, offset_x, offset_y,_ = await self.getScreenSize()
        outer_width = int(screen_width * 0.4)
        outer_height = int(screen_height * 0.4)
        center_width = max(int(outer_width * 0.8), 400)
        center_height = max(int(outer_height * 0.8), 400)
        overlap = int(outer_width * 0.1)
        base_positions = [
            (offset_x, offset_y),
            (offset_x + screen_width - outer_width, offset_y),
            (offset_x, offset_y + screen_height - outer_height),
            (offset_x + screen_width - outer_width, offset_y + screen_height - outer_height),
            (offset_x + (screen_width - center_width) // 2, offset_y + (screen_height - center_height) // 2),
        ]
        positions = [(x + random.randint(-overlap, overlap), y + random.randint(-overlap, overlap)) for x, y in base_positions]
        for client, (x, y) in zip(clients, positions):
            width, height = (center_width, center_height) if client == clients[4] else (outer_width, outer_height)
            await self.move_and_resize_window(client["address"], x, y, width, height)

    async def floatSixOrMoreWindows(self, clients):
        screen_width, screen_height, offset_x, offset_y,_ = await self.getScreenSize()
        num_clients = len(clients)
        grid_size = max(2, int((num_clients - 1) ** 0.5) + 1)
        window_width = screen_width // grid_size
        window_height = screen_height // grid_size
        overlap = int(window_width * 0.1)
        positions = [
            (offset_x + i % grid_size * window_width + random.randint(-overlap, overlap),
             offset_y + i // grid_size * window_height + random.randint(-overlap, overlap))
            for i in range(num_clients)
        ]
        for client, (x, y) in zip(clients, positions):
            await self.move_and_resize_window(client["address"], x, y, window_width, window_height)

    async def toggle_floating_workspace(self, clients):
        if self.is_floating: 
            for client in clients:
                address = client["address"]
                await hyprctl_cmd(f"dispatch settiled address:{address}", True)

        else:
            for client in clients:
                address = client["address"]
                await hyprctl_cmd(f"dispatch setfloating address:{address}", True)
            pass

    async def restoreWindowLayout(self, clients: List[Dict]):
        if self.current_workspace_id is None or self.current_workspace_id not in self.layout_history:
            return

        windows = self.layout_history[self.current_workspace_id]

        for stored in windows:
            address = stored["address"]
            x, y = stored["at"]
            width, height = stored["size"]

            # await hyprctlCommand(f"dispatch setfloating address:{address}", True)
            await self.move_and_resize_window(address, x, y, width , height)

    async def ensureFullWindow(self):
        if self.current_workspace_id is None or self.current_workspace_id not in self.layout_history:
            return

        windows = self.layout_history[self.current_workspace_id]
        if self.is_floating :
            return

        for stored in windows:
            address = stored["address"]
            await hyprctl_cmd(f"dispatch resizewindowpixel exact 100% 100%,address:{address}")

    async def move_and_resize_window(self, address: str, x: int, y: int, width: int, height: int):

        # print("toglep",self.isFloating)
        # minW = width if width > 1000 else 1000
        # minH = height if height > 500 else 500

        minW = width 
        minH = height
        # if self.isFloating is False:
        await hyprctl_cmd(f"dispatch movewindowpixel exact {x} {y},address:{address}")
        await hyprctl_cmd(f"dispatch resizewindowpixel exact {minW} {minH},address:{address}")

            
        # await hyprctlCommand(f"dispatch movewindowpixel exact {x} {y},address:{address}")
        # await hyprctlCommand(f"dispatch resizewindowpixel exact {width} {height},address:{address}")

    async def getScreenSize(self,hint: str | None = None) -> Tuple[int, int, int, int,str]:
        monitor_info = await hyprctl_cmd("monitors", True)
        current_monitor = None 
        if hint is not None : 
            current_monitor = next((m for m in monitor_info if m["name"] == hint), None)
        else:
            current_monitor = next((m for m in monitor_info if m["activeWorkspace"]["id"] == self.current_workspace_id), None)

        print("CM",current_monitor,monitor_info,self.current_workspace_id,hint)

        # Need to have a mechanism in which the layout system must remember or
        # contain a hint to select a monitor

        # print("M intro",monitor_info["x"])
        if not current_monitor:
            # return 1920, 1080, 0, 0,"default" # Default screen size if monitor info is not available
            return None

        return current_monitor["width"], current_monitor["height"], current_monitor["x"], current_monitor["y"],current_monitor["name"]

    async def printNeighbors(self, workspace_id: int) -> None:
        await printWindowLayout(self, workspace_id)

    async def findNeighbors(self, workspace_id: int) -> Dict[str, Dict[str, str]]:
        cl = self.window_control.props.get("clients")
        if cl is None:
            return {}
        clients = await cl.fetch()
        if clients is None:
            return {}

        workspace_clients = [
            {
                "address": client["address"],
                "size": client["size"],
                "at": client["at"],
                "class": client["class"],
                "workspace": client["workspace"]["id"],
                "focusHistoryID": client["focusHistoryID"],
                "floating": client["floating"]
            }
            for client in clients
            if client["workspace"]["id"] == workspace_id
        ]

        neighbors = {}
        threshold = 50  # Define a threshold for proximity

        for client in workspace_clients:
            neighbors[client["address"]] = {"left": None, "right": None, "top": None, "bottom": None}
            client_x, client_y = client["at"]
            client_width, client_height = client["size"]

            for other_client in workspace_clients:
                if client["address"] == other_client["address"]:
                    continue

                other_x, other_y = other_client["at"]
                other_width, other_height = other_client["size"]

                # Check if other_client is to the right and within proximity threshold
                if (client_y < other_y + other_height and
                        client_y + client_height > other_y and
                        abs(client_x + client_width - other_x) <= threshold):
                    neighbors[client["address"]]["right"] = other_client["address"]

                # Check if other_client is to the left and within proximity threshold
                if (client_y < other_y + other_height and
                        client_y + client_height > other_y and
                        abs(other_x + other_width - client_x) <= threshold):
                    neighbors[client["address"]]["left"] = other_client["address"]

                # Check if other_client is above and within proximity threshold
                if (client_x < other_x + other_width and
                        client_x + client_width > other_x and
                        abs(other_y + other_height - client_y) <= threshold):
                    neighbors[client["address"]]["top"] = other_client["address"]

                # Check if other_client is below and within proximity threshold
                if (client_x < other_x + other_width and
                        client_x + client_width > other_x and
                        abs(client_y + client_height - other_y) <= threshold):
                    neighbors[client["address"]]["bottom"] = other_client["address"]

        return neighbors
