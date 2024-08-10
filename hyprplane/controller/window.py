import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from functools import wraps
from multiprocessing.process import current_process

from ..cacher import CacheControl, HyprlandTask
from ..libnotify import notification
from ..utils import hyprctl_cmd

SOCKET_PATH = "/tmp/hyprland_controller.sock"

def timeIt(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()  # Record the start time
        result = func(*args, **kwargs)  # Call the function
        end_time = time.time()  # Record the end time
        elapsed_time = (
            end_time - start_time
        ) * 1000  # Calculate elapsed time in milliseconds
        print(f"Function '{func.__name__}' executed in {elapsed_time:.2f} ms")
        return result

    return wrapper


executor = ThreadPoolExecutor(4)


class WindowStack:
    def __init__(self) -> None:
        self.stacks = []
        self.pid = None
        self.pinLock = -1
        self.pinTable = {}

    def getPrev(self):
        if len(self.stacks) > 0:
            return self.stacks[-1]
        else:
            print("Window empty stacks!")

    def setPinLock(self):
        if self.pinLock == -1:
            self.pinLock = 1

    def setPinTarget(self, key):
        self.pinTable[key] = ""

    def appendToStack(self, curr):
        self.resizeStack()
        self.stacks.append(curr)

    def setPid(self):
        process = current_process()
        self.pid = process

    def resizeStack(self):
        BUFF_SIZE = 20
        if len(self.stacks) >= BUFF_SIZE:
            self.stacks.clear()

INITIAL_LOOKUP_TABLE = {
    "classLookup": {},
    "currentGroup": None,  # Currently active group
    "orders": [],
    "groupStates": {},  # Tracks state per group, e.g., {"lock1": {"index": 0}}
    "groups": {},  # Dictionary to store groups, e.g., {"lock1": [], "lock2": []}
    "groupOrders": [], # Order array to store the groupname and keep track
    "_gcount":0, # internal counter to keep track of groupOrders
    "_count": 0,
}

class WindowController:
    def __init__(self, wind_manager_executor=hyprctl_cmd) -> None:
        self.execute = wind_manager_executor
        self.pinLockTable = INITIAL_LOOKUP_TABLE
        self.props = {
            "monitors": CacheControl(
                HyprlandTask.create("monitors", output=True).asTask()
            ),
            "clients": CacheControl(
                HyprlandTask.create("clients", output=True).asTask()
            ),
        }

    def get_available_actions(self):
        return {
            "toggle": "Toggle between two windows",
            "lockpin": "Lock the current window",
            "toggle-lock": "Toggle between pinned windows",
            "pin": "Pinning window for toggle",
            "generate-lock": "Generate window lock group",
            # Add more actions as needed
        }

    def pingAlive(self):
        _vers = self.execute("version")
        return 0 if _vers is None else 1

    async def getWindowAddress(self, className: str):
        clientFetcher = self.props.get("clients")
        if clientFetcher is None:
            return None

        clients = await clientFetcher.fetch()

        if clients is None:
            return

        for client in clients:
            if client["class"] == className:
                return client["address"]

        print("No window with class {} founded!".format(className))
        return None

    async def getWindowWithinWorkspace(self,workspace:int):
        clientFetcher = self.props.get('clients')
        if clientFetcher is None:
            return None

        clients = await clientFetcher.fetch()
        workspaceClients = []
        if clients is None:
            return []

        for client in clients:
            print("client",client["workspace"]["id"],workspace)
            if client["workspace"]["id"] == workspace:
                workspaceClients.append(client)

        return workspaceClients

    async def focus_window(self, addrs: str):
        await self.execute(f"dispatch focuswindow address:{addrs}")
        await self.execute(f"dispatch bringactivetotop")
        return

    async def moveWindow(self, addrs, target_workspace: int):
        return await self.execute(
            f"dispatch movetoworkspace {target_workspace} {addrs}"
        )

    async def getActiveWindow(self):
        active_window = await self.execute("activewindow", getOutput=True)
        if active_window is None:
            return

        return active_window

    async def lockWindow(self):

        currentWin = await self.getActiveWindow()
        if currentWin is None:
            return

        className = currentWin["class"]
        address = currentWin["address"]

        currLockGroup = self.pinLockTable["currentGroup"]
        if currLockGroup is None: 
            self.createGroup("Default") 
            currLockGroup = "Default"

        groupTable = self.pinLockTable.get("groups", {}).get(currLockGroup, [])
        if groupTable is None:
            return

        # Check if the address is already in the group table
        if address not in groupTable:
            groupTable.append(address)
            self.pinLockTable["groups"][currLockGroup] = groupTable

        # Update classLookup only if it's a new entry or different from the existing one
        if (
            className not in self.pinLockTable["classLookup"]
            or self.pinLockTable["classLookup"][className] != address
        ):
            self.pinLockTable["classLookup"][className] = address

        notification("Lock window {}".format(currentWin["class"]))

    async def clearWindowPin(self):
        self.pinLockTable["orders"].clear()
        self.pinLockTable["classLookup"] = {}
        return

    async def unpinCurrWindow(self):
        currentWin = await self.getActiveWindow()
        print(currentWin)
        if currentWin is None:
            return

        name = currentWin["class"]
        currAddrs = currentWin["address"]
        _exist = self.pinLockTable["classLookup"].get(name)
        if _exist is not None:
            return

        self.pinLockTable["orders"] = list(
            filter(lambda winAddrs: winAddrs != currAddrs, self.pinLockTable["orders"])
        )
        del self.pinLockTable["classLookup"][name]

        print("lock name delete ", self.pinLockTable)

    def createGroup(self, groupName=None):
        if groupName is None:
            # Generate a unique random name
            while True:
                groupName = f"group_{uuid.uuid4().hex[:8]}"
                if groupName not in self.pinLockTable["groups"]:
                    break

        notification("New Group Created")

        if groupName not in self.pinLockTable["groups"]:
            self.pinLockTable["groups"][groupName] = []
            self.pinLockTable["groupStates"][groupName] = {"index": 0}

            # start adding current group
            self.pinLockTable["currentGroup"] = groupName
            self.pinLockTable["groupOrders"].append(groupName)
            print(f"Group '{groupName}' created.")
        else:
            print(f"Group '{groupName}' already exists.")

        return groupName

    async def toggleGroup(self):
        # Check if there are any groups
        if not self.pinLockTable["groupOrders"]:
            print("No groups available to toggle.")
            return

        # Get the current group
        currentGroup = self.pinLockTable.get("currentGroup")

        # Find the index of the current group in groupOrders
        if currentGroup in self.pinLockTable["groupOrders"]:
            currentIndex = self.pinLockTable["groupOrders"].index(currentGroup)
        else:
            currentIndex = -1  # Start from the beginning if current group is not found

        # Calculate the next group index
        nextIndex = (currentIndex + 1) % len(self.pinLockTable["groupOrders"])
        next_group = self.pinLockTable["groupOrders"][nextIndex]

        # Update the current group
        self.pinLockTable["currentGroup"] = next_group

        print(f"Toggled to group: {next_group}")

        # Optionally, you might want to update _gcount, though it's not clear from the context how it should be used
        self.pinLockTable["_gcount"] = nextIndex

    def getWinFromGroup(self, group):
        if group in self.pinLockTable["groups"]:
            return self.pinLockTable["groups"][group]

    def addWindowToGroup(self, groupName, windowAddress):
        if groupName in self.pinLockTable["groups"]:
            if windowAddress not in self.pinLockTable["groups"][groupName]:
                lockGroup = self.pinLockTable["groups"][groupName]
                if windowAddress in lockGroup:
                    print(
                        f"Group '{groupName}' already has window with address {windowAddress}."
                    )
                    return
                lockGroup.append(windowAddress)
                print(f"Window {windowAddress} added to group '{groupName}'.")
        else:
            print(f"Group '{groupName}' does not exist.")

    def switchGroup(self, groupName):
        if groupName in self.pinLockTable["groups"]:
            self.pinLockTable["currentGroup"] = groupName
            print(f"Switched to group '{groupName}'.")
        else:
            print(f"Group '{groupName}' does not exist.")

    def removeWindowFromGroup(self, group_name, window_address):
        if group_name in self.pinLockTable["groups"]:
            if window_address in self.pinLockTable["groups"][group_name]:
                self.pinLockTable["groups"][group_name].remove(window_address)
                print(f"Window {window_address} removed from group '{group_name}'.")
        else:
            print(f"Group '{group_name}' does not exist.")

    def clearGroup(self, group_name):
        if group_name in self.pinLockTable["groups"]:
            # self.pinLockTable["groups"][group_name].clear()
            self.pinLockTable = INITIAL_LOOKUP_TABLE
            print(f"Group '{group_name}' cleared.")
        else:
            print(f"Group '{group_name}' does not exist.")

    def clearLockGroup(self, group_name):
        if group_name in self.pinLockTable["groups"]:
            del self.pinLockTable["groups"][group_name]
            del self.pinLockTable["groupState"][group_name]
            for i,order in enumerate(self.pinLockTable["groupOrders"]):
                if order == group_name:
                    self.pinLockTable["groupOrders"].pop(i)
                    return
            print(f"Group '{group_name}' cleared.")
        else:
            print(f"Group '{group_name}' does not exist.")
    
    def deleteGroup(self, group_name):
        if group_name in self.pinLockTable["groups"]:
            del self.pinLockTable["groups"][group_name]
            if self.pinLockTable["currentGroup"] == group_name:
                self.pinLockTable["currentGroup"] = None
            print(f"Group '{group_name}' deleted.")
        else:
            print(f"Group '{group_name}' does not exist.")

    async def togglePinnedWindow(self, direction="forward"):
        currentGroup = self.pinLockTable["currentGroup"]
        if currentGroup is None:
            print("No group selected. Please select a group to toggle windows.")
            return

        windows = self.pinLockTable["groups"].get(currentGroup, [])
        currentIndex = self.pinLockTable["nextIndex"]

        if not windows:
            print(f"No windows in group '{currentGroup}' to toggle.")
            return

        if direction == "forward":
            nextIndex = (currentIndex + 1) % len(windows)
        elif direction == "backward":
            nextIndex = (currentIndex - 1) % len(windows)
        else:
            print("Invalid direction. Use 'forward' or 'backward'.")
            return

        next_window = windows[nextIndex]

        print(
            f"Toggling from index {currentIndex} to {nextIndex} in group '{currentGroup}'."
        )
        await self.focus_window(next_window)
        self.pinLockTable["nextIndex"] = nextIndex

    async def toggleWithinGroup(self, direction="forward"):
        currentGroup = self.pinLockTable["currentGroup"]
        if not currentGroup:
            print("No group selected.")
            return

        windows = self.pinLockTable["groups"][currentGroup]
        groupState = self.pinLockTable["groupStates"][currentGroup]
        currentIndex = groupState["index"]

        if not windows:
            print(f"No windows in group '{currentGroup}' to toggle.")
            return

        currentWindow = await self.getActiveWindow()
        if currentWindow is None:
            return

        currentAddress = currentWindow["address"]

        def getNextIndex(start_index, step):
            index = start_index
            for _ in range(len(windows)):
                index = (index + step) % len(windows)
                if windows[index] != currentAddress:
                    return index
            return None

        if direction == "forward":
            nextIndex = getNextIndex(currentIndex, 1)
        elif direction == "backward":
            nextIndex = getNextIndex(currentIndex, -1)
        else:
            print("Invalid direction. Use 'forward' or 'backward'.")
            return

        if nextIndex is None:
            print(f"No different windows found in group '{currentGroup}'.")
            return

        print(
            f"Toggling from index {currentIndex} to {nextIndex} in group '{currentGroup}'."
        )

        nextWindow = windows[nextIndex]
        await self.focus_window(nextWindow)
        groupState["index"] = nextIndex

    def listGroups(self):
        print("Available groups:")
        for group in self.pinLockTable["groups"]:
            print(f" - {group}")

    def listWindowsInGroup(self, groupName):
        if groupName in self.pinLockTable["groups"]:
            windows = self.pinLockTable["groups"][groupName]
            print(f"Windows in group '{groupName}':")
            for window in windows:
                print(f" - {window}")
        else:
            print(f"Group '{groupName}' does not exist.")


# lock ->
# pairs : [ a,b ], a = ("window class","address")
# => lookup(class) -> address
# next : "window class" # next wind
# orders : [class1,class2,class3]
