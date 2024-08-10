import asyncio
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
        self.sideWindows = sideWindows


class StageController(LayoutController):
    def __init__(self, windCont: WindowController) -> None:
        super().__init__(windCont)
        self.hyprland_event = HyprlandEventHandler()
        self.current_mode: Dict[int, LayoutMode] = {}
        self.current_workspace_id: Optional[int] = None
        # convert all window groups into a dictionary that directly disected
        # through workspace id, each stage group panel
        self.window_groups: Dict[int,List[WindowGroup]] = {}
        self.active_group_index: int = 0
        self.window_open_queue = deque(maxlen=5)  # Store last 5 window open events
        self.event = threading.Event()
        self.prevPos: Dict[int,List] = {}
        self.activeGroupIndice = Dict[int,int]
        self.isProcessing = False
        self.last_win_open_ts = 0
        self.task_queue = Queue(maxsize=50)

    def setEvent(self, event: threading.Event):
        pass
        # self.event = event

    async def start(self):
        # threading.Thread(target=self._run_executor_loop).run()
        # await self.eventServer()
        self.hyprland_event.subscribe("openwindow", self.ensure_position_locked)
        self.hyprland_event.start()

    def _run_executor_loop(self):
        """Run the asyncio event loop in the new thread."""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self.event_handler())

    async def event_handler(self):
        while self.loop.is_running:
            try:
                # Use get_nowait() for non-blocking operation
                event = self.hyprland_event.msgQueue.get_nowait()
            except queue.Empty:
                # If queue is empty, wait a bit before trying again
                await asyncio.sleep(0.1)
                continue

            et, ed = event.split(">>")

            if et == "openwindow" or et == "closewindow":
                self.debounce_time = 0.001
                current_time = asyncio.get_event_loop().time()
                if current_time - self.last_win_open_ts > self.debounce_time:
                    self.last_win_open_ts = current_time
                    await self.handle_open_event()

            if et == "workspace":
                print("ET",et)
                await self.execute_queued_task(ed)
                pass

    async def handle_open_event(self):

        initialWorkspace = self.current_workspace_id
        if initialWorkspace is None: 
            return

        prevPosition = self.prevPos[initialWorkspace]
        initialPosCount = len(prevPosition)

        self.max_retries = 5

        for attempt in range(self.max_retries):
            aWindow = await self.getActiveWindow()
            if aWindow is None: 
                continue

            currWid=aWindow["workspace"]["id"]

            print("OPEN",aWindow is None,currWid)
            print("INITIAL",initialWorkspace,currWid)

            if initialWorkspace != currWid:
                # detected work space change
                # therefore we queue the task
                print("EMP",initialWorkspace)

                func = self.enter_stage_mode(initialWorkspace,prevPosition[0]["monitor"])
                self.task_queue.put(asyncio.create_task(func))

                return

            await self.enter_stage_mode()
            wid =  self.current_workspace_id
            if wid is None:
                return

            prevPosition = self.prevPos.get(wid) 
            if prevPosition is None: 
                return

            if len(prevPosition) != initialPosCount:
                print("SUCCESS")
                return  # Success

            if attempt < self.max_retries - 1:
                await asyncio.sleep(1)  # Short delay between retries

        print("Failed to update window positions after retries")


    def set_workspace_mode(self, wid,mode: LayoutMode):
        self.current_mode[wid] = mode

    async def set_current_workspace_mode(self, mode: LayoutMode):
        win = await self.window_control.getActiveWindow()
        if win is None:
            return

        wid = win["workspace"]["id"]
        self.current_workspace_id = wid
        self.set_workspace_mode(wid,mode) 

    async def get_current_workspace_mode(self):
        win = await self.window_control.getActiveWindow()
        default_mode = LayoutMode.TILED
        if win is None:
            return default_mode

        wid = win["workspace"]["id"]
        self.current_workspace_id = wid
        res = self.current_mode.get(wid)

        print("CURR",wid,res)
        print("M",res)
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

    def get_win_groups(self,workspace: Optional[int]=None):
        if workspace is None:
            workspace = self.current_workspace_id

        if workspace is None:
            return []

        groups = self.window_groups.get(workspace) 
        if groups is None:
            return []

        return groups

    def set_curr_window_groups(self,groups: list[WindowGroup]):
        if self.current_workspace_id is None:
            return 
        
        self.window_groups[self.current_workspace_id] = groups

    async def load_win_groups(self,wid : int | None =None):
        clients = await self.get_workspace_clients(wid)
        if not clients:
            return

        print("WWWID --> ",wid)
        self.set_curr_window_groups(self.create_window_group(clients))

    async def enter_stage_mode(self,wid: int | None = None,
                                    monitorHint:str
                                    | None=None):
        print('widdddd -> ',wid)

        if wid is not None:
            self.current_workspace_id = wid
            self.set_workspace_mode(wid,LayoutMode.STAGE_MANAGER)
        else:
            await self.set_current_workspace_mode(LayoutMode.STAGE_MANAGER)

        await self.load_win_groups(wid)
        await self.apply_stage_manager_layout(wid,monitorHint)

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

    async def execute_queued_task(self,eventData):
        print("EX",eventData)

        try : 
            while True: 
                func= self.task_queue.get_nowait()
                if func is None:
                    break

                print("ITMM",func)
                await func

        except Empty as e:
            print("EMPTY",e)
        except Exception as e:
            print("Task error: ",e)

    async def event_server(self):
        self.hyprland_event.subscribe("openwindow", self.ensure_position_locked)
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
        if self.current_workspace_id is None :
            return

        print("WWW",self.window_groups)
        for group in self.window_groups[self.current_workspace_id]:
            for window in [group.main_window] + group.sideWindows:
                await hyprctl_cmd(
                    f"dispatch settiled address:{window['address']}", True
                )

        self.window_groups[self.current_workspace_id] = []

    async def handleWindowChange(self, event_type):
        currTS = asyncio.get_event_loop().time()
        print("CCU,cu", currTS)
        update_interval = 0.1
        if currTS - self.last_win_open_ts < update_interval:
            return  # Debounce: skip if too soon after last update

        if event_type == "openwindow":
            self.current_windows.add(event_data)
        elif event_type == "closewindow":
            self.current_windows.discard(event_data)
        pass

    def savePrevPosition(self,workspaceId:int,pos):
        self.prevPos[workspaceId] = pos

    async def apply_stage_manager_layout(self,workspace_id: int | None =
                                      None,monitorHint: str | None = None):
        if not self.window_groups:
            return

        prevId =  self.current_workspace_id

        if workspace_id is not None:
            self.current_workspace_id = workspace_id

        # await self.loadWindowGroup()
        screen_width, screen_height, offsetX, offsetY,monitorName = await self.getScreenSize(monitorHint)

        # Main window dimensions (larger and positioned to the right)
        main_width = int(screen_width * 0.8)
        main_height = int(screen_height * 0.9)
        mainX = offsetX + (screen_width - main_width) - 20  # 20px padding from right edge
        mainY = offsetY + (screen_height - main_height) // 2
        # Minified window dimensions (smaller and to the left)
        miniWidth = int(screen_width * 0.18)
        miniHeight = int(screen_height * 0.24)
        miniX = offsetX + 0  # 20px padding from left edge
        miniY = offsetY + 0  # 20px padding from top edge
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

        print("MAIN WIN",activeGroup.main_window["address"],
              mainX,mainY,main_width,main_height)

        # await self.focusWindow(activeGroup.mainWindow["address"])
        await hyprctl_cmd(
            f"dispatch movetoTop address:{activeGroup.main_window['address']}"
        )

        # Position minified windows for all groups in a vertical stack
        mini_windows = []
        for i, group in enumerate(current_work_group):
            if i != self.active_group_index:
                mini_windows.append(group.main_window)
            mini_windows.extend(group.sideWindows)

        max_window_per_col = (screen_height - miniY) // (miniHeight + miniVerticalGap)
        currId = workspace_id or self.current_workspace_id

        if currId is None:
            return

        self.savePrevPosition(currId,[])

        for i, window in enumerate(mini_windows):
            column = i // max_window_per_col
            row = i % max_window_per_col

            xPosition = miniX + column * (miniWidth + miniHorizontalGap)
            yPosition = miniY + row * (miniHeight + miniVerticalGap)

            self.prevPos[currId].append({"x": xPosition, "y": yPosition, "w":
                                         miniWidth, "h": miniHeight,"monitor":
                                         monitorName})

            await self.move_and_resize_window(
                window["address"], xPosition, yPosition, miniWidth, miniHeight
            )
        if workspace_id is not None:
           self.current_workspace_id = prevId
        # Raise the active window to the top

    async def cycleMainWindow(self):
        if self.current_workspace_id is None:
            return
        
        if self.current_mode.get(self.current_workspace_id) != LayoutMode.STAGE_MANAGER or not self.window_groups.get(self.current_workspace_id):
            return


        workspace_groups= self.get_win_groups()
        if not workspace_groups:
            return

        active_group = workspace_groups[self.active_group_index]
        all_windows = [active_group.main_window] + active_group.sideWindows
        newMain = all_windows.pop(0)
        all_windows.append(newMain)
        newActive = WindowGroup(all_windows[0], all_windows[1:])
        self.window_groups[self.current_workspace_id][self.active_group_index] = newActive

        # workspace_groups
        print("ALL MAIN,",newActive.main_window)
        
        await self.focus_window(newActive.main_window["address"])
        await self.apply_stage_manager_layout()

    async def get_workspace_clients(self,specifiedId: int | None = None) -> List[Dict]:
        activeWorkspace = specifiedId

        if specifiedId is None: 
            activeWindow = await self.window_control.getActiveWindow()
            if activeWindow is None:
                return []

            activeWorkspace = activeWindow["workspace"]["id"]
            self.current_workspace_id = activeWorkspace

        
        cl = self.window_control.props.get("clients")

        if cl is None:
            return []

        clients = await cl.fetch()

        if clients is None:
            return []

        return [
            client
            for client in clients
            if client["workspace"]["id"] == activeWorkspace
        ]
