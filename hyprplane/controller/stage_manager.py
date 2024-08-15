import asyncio
import json
import queue
import random
import threading
from collections import deque
from concurrent.futures import Executor, ThreadPoolExecutor
from enum import Enum
from queue import Empty, Queue
from subprocess import Popen
from threading import Thread
from typing import Dict, List, Optional, Tuple

from hyprplane.controller.layout import LayoutController
from hyprplane.controller.window import WindowController
from hyprplane.drawer import printWindowLayout
from hyprplane.event import HyprlandEventHandler

from ..utils import hyprctl_cmd


class LayoutMode(Enum):
    TILED = 1
    STAGE_MANAGER = 2


class WindowGroup:
    def __init__(self, mainWindow: Dict, sideWindows: List[Dict]):
        self.main_window = mainWindow
        self.side_windows = sideWindows


class StageController(LayoutController):
    def __init__(self, windCont: WindowController) -> None:
        super().__init__(windCont)
        self.hyprland_event = HyprlandEventHandler()
        self.current_mode: Dict[int, LayoutMode] = {}
        self.current_workspace_id: Optional[int] = None
        # convert all window groups into a dictionary that directly disected
        # through workspace id, each stage group panel
        self.window_groups: Dict[int, List[WindowGroup]] = {}
        self.active_group_index: int = 0
        self.window_open_queue = deque(maxlen=5)  # Store last 5 window open events
        self.event = threading.Event()
        self.prevPos: Dict[int, List] = {}
        self.active_group_indice = Dict[int, int]
        self.is_processing = False
        self._executor_running = True
        self.last_win_open_ts = 0
        self.task_queue = Queue(maxsize=50)
    
    def stop(self):
        self.hyprland_event.stop()
        self._executor_running = False


    async def start(self):
        # threading.Thread(target=self._run_executor_loop).run()
        # await self.eventServer()
        # self.hyprland_event.subscribe("openwindow", self.ensure_position_locked)
        self.hyprland_event.start()

    def _run_executor_loop(self):
        print("Spawnning executor")
        """Run the asyncio event loop in the new thread."""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self.event_handler())

    async def event_handler(self):
        print("EVVVV",self._executor_running)
        while self.loop.is_running and self._executor_running:
            try:
                # Use get_nowait() for non-blocking operation
                event = self.hyprland_event.msg_queue.get_nowait()
                print("EVENT",event)
            except queue.Empty:
                # If queue is empty, wait a bit before trying again
                await asyncio.sleep(0.1)
                continue

            et, ed = event.split(">>")
            print("ET -> ",et)
            if et == "openwindow" or et == "closewindow":
                await self.handle_window_change(et, ed)

            # if et == "closewindow":
            #     self.debounce_time = 0.001
            #     current_time = asyncio.get_event_loop().time()
            #     if current_time - self.last_win_open_ts > self.debounce_time:
            #         self.last_win_open_ts = current_time
            #         await self.handle_open_event()

            # if et == "workspace":
            #     print("ET", et)
            #     await self.execute_queued_task(ed)

    async def handle_window_change(self, event_type, addrs):
        # print("handling window change", event_type)
        # print("system workspace", self.current_workspace_id)
        # print("system ", self.prevPos)

        if self.current_workspace_id is None:
            return
        
        prev_pos = self.prevPos[self.current_workspace_id]

        if len(prev_pos) < 1 : 
            return [], prev_pos 

        last_pos = prev_pos[-1]
        awt = await self.get_active_window()

        if awt is None:
            return

        temp_addrs = awt["address"]

        # print("last pos", last_pos,
        #       addrs,event_type,self.current_mode[self.current_workspace_id])
        print("Input window spacec",event_type)
        new_position = None

        await self.load_win_groups()

        if event_type == "openwindow":
            new_position = await self.next_window_position(prev_pos, awt, None)
            await hyprctl_cmd(f"dispatch setfloating address:{temp_addrs}")
            await self.move_and_resize_window(
                temp_addrs,
                new_position["x"],
                new_position["y"],
                new_position["w"],
                new_position["h"],
            )

            self.prevPos[self.current_workspace_id].append(new_position)
            self.props["clients"].revoke()

            await hyprctl_cmd("dispatch alterzorder bottom")

        else:
            # self.set_workspace_mode(self.current_workspace_id,LayoutMode.STAGE_MANAGER)
            # await self.enter_stage_mode()
            new_positions, updated_prev_pos = await self.determine_negative_positions(temp_addrs, prev_pos)

            print("New positions:", new_positions)
            print("Updated previous positions:", updated_prev_pos)
            
            for position in new_positions:
                await self.move_and_resize_window(
                    position["address"],  # Use the correct address for each window
                    position["x"],
                    position["y"],
                    position["w"],
                    position["h"]
                )
            
            if updated_prev_pos and self.current_workspace_id:
                self.savePrevPosition(self.current_workspace_id,updated_prev_pos)

                print("next window", new_positions)


        self.set_workspace_mode(self.current_workspace_id, LayoutMode.STAGE_MANAGER)

    async def bring_main_to_back(self):
        await hyprctl_cmd("dispatch alterzorder bottom")

    async def verify_window_state(self):
        actual_windows = await self.get_workspace_clients()  
        # Implement this method to get all current windows
        for workspace_id, positions in self.prevPos.items():
            self.prevPos[workspace_id] = [pos for pos in positions if pos['address'] in actual_windows]

        print(f"Verified window state: {self.prevPos}")

    async def determine_negative_positions(self, window_address_to_delete: str, prev_positions: list[dict]) -> tuple[list[dict], list[dict]]:
        print(f"Recalculating positions after deleting window: {window_address_to_delete}")
        print(f"Previous positions: {prev_positions}")
        
        screen_width, screen_height, offsetX, offsetY, monitorName = await self.getScreenSize()
        
        # Window dimensions and gaps
        miniWidth = int(screen_width * 0.18)
        miniHeight = int(screen_height * 0.24)
        miniX = offsetX
        miniY = offsetY
        miniVerticalGap = 30
        miniHorizontalGap = 30
        max_window_per_col = (screen_height - miniY) // (miniHeight + miniVerticalGap)
        # max_cols = (screen_width - miniX) // (miniWidth + miniHorizontalGap)

        # max_window_per_col = 3
        max_cols = (screen_width - miniX) // (miniWidth + miniHorizontalGap)

        # Create a grid to represent window positions
        grid = [[None for _ in range(max_window_per_col)] for _ in range(max_cols)]
        print("Grid rom",grid,max_window_per_col,max_cols)
        # Function to get grid position
        def get_grid_position(x, y):
            col = (x - miniX) // (miniWidth + miniHorizontalGap)
            row = (y - miniY) // (miniHeight + miniVerticalGap)
            return min(col, max_cols - 1), min(row, max_window_per_col - 1)

        for window in prev_positions:
            if window['address'] != window_address_to_delete:
                col, row = get_grid_position(window['x'], window['y'])
                grid[col][row] = window

        updated_positions = []
        windows_to_move = []

        # Reposition windows
        for col in range(max_cols):
            next_empty_row = 0
            for row in range(max_window_per_col):
                if grid[col][row] is not None:
                    window = grid[col][row]
                    new_x = miniX + col * (miniWidth + miniHorizontalGap)
                    new_y = miniY + next_empty_row * (miniHeight + miniVerticalGap)
                    
                    if window['x'] != new_x or window['y'] != new_y:
                        new_position = {
                            'address': window['address'],
                            'x': new_x,
                            'y': new_y,
                            'w': miniWidth,
                            'h': miniHeight,
                            'monitor': window['monitor']
                        }
                        windows_to_move.append(new_position)
                        window.update(new_position)
                    
                    updated_positions.append(window)
                    next_empty_row += 1

        # Check for any windows that weren't in the grid (e.g., if they were outside the valid area)
        for window in prev_positions:
            if window['address'] != window_address_to_delete and window not in updated_positions:
                col, row = get_grid_position(window['x'], window['y'])
                new_x = miniX + col * (miniWidth + miniHorizontalGap)
                new_y = miniY + row * (miniHeight + miniVerticalGap)
                
                new_position = {
                    'address': window['address'],
                    'x': new_x,
                    'y': new_y,
                    'w': miniWidth,
                    'h': miniHeight,
                    'monitor': window['monitor']
                }
                windows_to_move.append(new_position)
                updated_positions.append(new_position)

        print(f"Windows to move: {windows_to_move}")
        print(f"Updated positions: {updated_positions}")
        return windows_to_move, updated_positions


    async def handle_open_event(self):

        initialWorkspace = self.current_workspace_id
        if initialWorkspace is None:
            return

        prev_pos = self.prevPos[initialWorkspace]
        initialPosCount = len(prev_pos)

        self.max_retries = 5

        for attempt in range(self.max_retries):
            aWindow = await self.get_active_window()
            if aWindow is None:
                continue

            currWid = aWindow["workspace"]["id"]

            print("OPEN", aWindow is None, currWid)
            print("INITIAL", initialWorkspace, currWid)

            if initialWorkspace != currWid:
                # detected work space change
                # therefore we queue the task
                print("EMP", initialWorkspace)

                prefer_monitor = prev_pos[0]["monitor"]
                func = self.enter_stage_mode(initialWorkspace, prefer_monitor)
                self.task_queue.put(asyncio.create_task(func))

                return

            await self.enter_stage_mode()
            wid = self.current_workspace_id
            if wid is None:
                return

            prev_pos = self.prevPos.get(wid)
            if prev_pos is None:
                return

            if len(prev_pos) != initialPosCount:
                print("SUCCESS")
                return  # Success

            if attempt < self.max_retries - 1:
                await asyncio.sleep(1)  # Short delay between retries

        print("Failed to update window positions after retries")

    def set_workspace_mode(self, wid, mode: LayoutMode):
        self.current_mode[wid] = mode

    async def set_current_workspace_mode(self, mode: LayoutMode):
        win = await self.window_control.get_active_window()
        if win is None:
            return

        wid = win["workspace"]["id"]
        self.current_workspace_id = wid
        self.set_workspace_mode(wid, mode)

    async def get_current_workspace_mode(self):
        win = await self.window_control.get_active_window()
        default_mode = LayoutMode.TILED
        if win is None:
            return default_mode

        wid = win["workspace"]["id"]
        self.current_workspace_id = wid
        res = self.current_mode.get(wid)

        print("CURR", wid, res)
        print("M", res)
        if res is None:
            await self.set_current_workspace_mode(default_mode)
        else:
            return res

        return default_mode

    async def toggle_layout_mode(self):
        currMode = await self.get_current_workspace_mode()
        print("MODE", self.current_mode)

        if currMode == LayoutMode.TILED:
            # Popen(["hyprpm", "enable", "hyprbars"])
            await self.enter_stage_mode()
        elif currMode == LayoutMode.STAGE_MANAGER:
            # Popen(["hyprpm", "disable", "hyprbars"])
            await self.exit_stage_mode()

    def get_win_groups(self, workspace: Optional[int] = None):
        if workspace is None:
            workspace = self.current_workspace_id

        if workspace is None:
            return []

        groups = self.window_groups.get(workspace)
        if groups is None:
            return []

        return groups

    def set_curr_window_groups(self, groups: list[WindowGroup]):
        if self.current_workspace_id is None:
            return

        self.window_groups[self.current_workspace_id] = groups

    async def load_win_groups(self, wid: int | None = None):
        clients = await self.get_workspace_clients(wid)
        print("CLIENTS",len(clients))
        if not clients:
            return

        renewed_group = self.create_window_group(clients)
        print("WWWID --> ", wid,renewed_group)
        self.set_curr_window_groups(renewed_group)

    async def enter_stage_mode(
        self, wid: int | None = None, monitorHint: str | None = None
    ):
        print("widdddd -> ", wid)

        if wid is not None:
            self.current_workspace_id = wid
            self.set_workspace_mode(wid, LayoutMode.STAGE_MANAGER)
        else:
            await self.set_current_workspace_mode(LayoutMode.STAGE_MANAGER)

        await self.load_win_groups(wid)
        await self.apply_stage_manager_layout(wid, monitorHint)

    async def ensure_position_locked(self, eventData):

        self.event.wait()
        data_array = eventData.split(",")
        addrs = data_array[0].strip()
        curr_mode = await self.get_current_workspace_mode()

        if curr_mode == LayoutMode.STAGE_MANAGER:
            await hyprctl_cmd(f"dispatch setfloating address:{addrs}")
            await self.load_win_groups()
            # await self.add_window_to_stage(event_data)
            # self.currentMode = LayoutMode.STAGE_MANAGER
            await self.set_current_workspace_mode(LayoutMode.STAGE_MANAGER)
            await self.enter_stage_mode()

        self.event.clear()

    async def execute_queued_task(self, eventData):
        print("EX", eventData,self.set_workspace_mode)

        try:
            while True:
                func = self.task_queue.get_nowait()
                if func is None:
                    break

                print("ITMM", func)
                await func

        except Empty as e:
            print("EMPTY", e)
        except Exception as e:
            print("Task error: ", e)

    async def event_server(self):
        pass
        # self.hyprland_event.subscribe("openwindow", self.ensure_position_locked)
        # self.hyprlandEvent.subscribe("workspace", self.executeInBetweenTask)
        # await self.hyprlandEvent.read_events()

    def create_window_group(self, clients: List[Dict]) -> List[WindowGroup]:
        groups = []
        miniWindowChunks = 10

        # Create groups of up to 3 windows
        for i in range(0, len(clients), miniWindowChunks):
            group_clients = clients[i : i + miniWindowChunks]
            groups.append(WindowGroup(group_clients[0], group_clients[1:]))

        return groups

    async def exit_stage_mode(self):
        await self.set_current_workspace_mode(LayoutMode.TILED)
        if self.current_workspace_id is None:
            return

        print("WWW", self.window_groups)
        for group in self.window_groups[self.current_workspace_id]:
            for window in [group.main_window] + group.side_windows:
                await hyprctl_cmd(
                    f"dispatch settiled address:{window['address']}", True
                )

        self.window_groups[self.current_workspace_id] = []

    def savePrevPosition(self, workspaceId: int, pos):
        self.prevPos[workspaceId] = pos

    async def next_window_position(self, prevPos, newWindow, screen_info):
        """
        Calculate the position for the next window based on existing window positions.

        :param prevPos: List of dictionaries containing previous window positions
        :param newWindow: Dictionary containing new window information
        :param screen_info: Dictionary containing screen dimensions and offsets
        :return: Dictionary with x, y, w, h, and monitor for the new window
        """

        screen_width, screen_height, offsetX, offsetY, monitorName = (
            await self.getScreenSize()
        )

        # Window dimensions
        miniWidth = int(screen_width * 0.18)
        miniHeight = int(screen_height * 0.24)
        miniX = offsetX + 0  # 20px padding from left edge
        miniY = offsetY + 0  # 20px padding from top edge
        miniVerticalGap = 30  # Gap between minified windows
        miniHorizontalGap = 30  # Gap between columns when overflow occurs
        

        max_window_per_col = (screen_height - miniY) // (miniHeight + miniVerticalGap)
        print("EPOCHI",newWindow)
        if not prevPos:
            # If there are no previous windows, place the new window at the start
            return {
                "x": miniX,
                "y": miniY,
                "w": miniWidth,
                "h": miniHeight,
                "monitor": monitorName,
                "address":newWindow["address"]
            }

        # Find the last window position
        last_window = prevPos[-1]
        last_column = (last_window["x"] - miniX) // (miniWidth + miniHorizontalGap)
        last_row = (last_window["y"] - miniY) // (miniHeight + miniVerticalGap)

        # Calculate the next position
        if last_row + 1 < max_window_per_col:
            # There's space in the current column
            new_x = last_window["x"]
            new_y = miniY + (last_row + 1) * (miniHeight + miniVerticalGap)
        else:
            # Move to the next column
            new_x = miniX + (last_column + 1) * (miniWidth + miniHorizontalGap)
            new_y = miniY

        return {
            "x": new_x,
            "y": new_y,
            "w": miniWidth,
            "h": miniHeight,
            "monitor": monitorName,
            "address":newWindow["address"]
        }

    async def apply_stage_manager_layout(
        self,
        workspace_id: int | None = None,
        monitorHint: str | None = None,
        debounce_time: int | None = None,
    ):
        if not self.window_groups:
            return

        prevId = self.current_workspace_id

        if workspace_id is not None:
            self.current_workspace_id = workspace_id

        # await self.loadWindowGroup()
        screen_width, screen_height, offset_x, offset_y, monitor_name = (
            await self.getScreenSize(monitorHint)
        )

        # Main window dimensions (larger and positioned to the right)
        main_width = int(screen_width * 0.8)
        main_height = int(screen_height * 0.9)
        mainX = (
            offset_x + (screen_width - main_width) - 20
        )  # 20px padding from right edge
        mainY = offset_y + (screen_height - main_height) // 2
        # Minified window dimensions (smaller and to the left)
        miniWidth = int(screen_width * 0.18)
        miniHeight = int(screen_height * 0.24)
        miniX = offset_x + 0  # 20px padding from left edge
        miniY = offset_y + 0  # 20px padding from top edge
        miniVerticalGap = 30  # Gap between minified windows
        miniHorizontalGap = 30  # Gap between columns when overflow occurs

        clients = await self.get_workspace_clients(workspace_id)
        await self.toggle_floating_workspace(clients)

        # Position the active group's main window
        current_work_group = self.get_win_groups(workspace_id)
        activeGroup = current_work_group[self.active_group_index]

        await self.move_and_resize_window(
            activeGroup.main_window["address"], mainX, mainY, main_width, main_height
        )

        print(
            "MAIN WIN",
            activeGroup.main_window["address"],
            mainX,
            mainY,
            main_width,
            main_height,
        )

        # await self.focusWindow(activeGroup.mainWindow["address"])
        await hyprctl_cmd(
            f"dispatch alterzorder top address:{activeGroup.main_window['address']}"
        )

        await self.focus_window(activeGroup.main_window["address"])
        # Position minified windows for all groups in a vertical stack
        mini_windows = []
        for i, group in enumerate(current_work_group):
            if i != self.active_group_index:
                mini_windows.append(group.main_window)
            mini_windows.extend(group.side_windows)

        max_window_per_col = (screen_height - miniY) // (miniHeight + miniVerticalGap)
        currId = workspace_id or self.current_workspace_id

        if currId is None:
            return

        self.savePrevPosition(currId, [])
        
        for i, window in enumerate(mini_windows):
            column = i // max_window_per_col
            row = i % max_window_per_col

            xPosition = miniX + column * (miniWidth + miniHorizontalGap)
            yPosition = miniY + row * (miniHeight + miniVerticalGap)
            # await asyncio.sleep(0.01)
            self.prevPos[currId].append(
                {
                    "x": xPosition,
                    "y": yPosition,
                    "w": miniWidth,
                    "h": miniHeight,
                    "monitor": monitor_name,
                    "address": window["address"]
                }
            )

            await self.move_and_resize_window(
                window["address"], xPosition, yPosition, miniWidth, miniHeight
            )
        if workspace_id is not None:
            self.current_workspace_id = prevId
        # Raise the active window to the top

    async def cycle_main_window(self):
        if self.current_workspace_id is None:
            return

        if self.current_mode.get(
            self.current_workspace_id
        ) != LayoutMode.STAGE_MANAGER or not self.window_groups.get(
            self.current_workspace_id
        ):
            return

        workspace_groups = self.get_win_groups()
        if not workspace_groups:
            return

        active_group = workspace_groups[self.active_group_index]
        all_windows = [active_group.main_window] + active_group.side_windows
        newMain = all_windows.pop(0)
        all_windows.append(newMain)
        newActive = WindowGroup(all_windows[0], all_windows[1:])
        self.window_groups[self.current_workspace_id][
            self.active_group_index
        ] = newActive

        # workspace_groups
        print("ALL MAIN,", newActive.main_window)

        await self.focus_window(newActive.main_window["address"])
        await self.apply_stage_manager_layout()

    async def get_workspace_clients(self, specifiedId: int | None = None) -> List[Dict]:
        activeWorkspace = specifiedId
            
        if specifiedId is None:
            activeWindow = await self.window_control.get_active_window()
            if activeWindow is None:
                return []

            activeWorkspace = activeWindow["workspace"]["id"]
            self.current_workspace_id = activeWorkspace

        self.window_control.props.get("clients")
        cl = self.window_control.props.get("clients")
        
        if cl is None:
            return []

        cl.revoke()
        clients = await cl.fetch()
        
        if clients is None:
            return []

        return [
            client for client in clients if client["workspace"]["id"] == activeWorkspace
        ]
