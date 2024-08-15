import json
from abc import ABC, abstractmethod
from asyncio.subprocess import PIPE
from subprocess import Popen

from hyprplane.controller.layout import LayoutController
from hyprplane.controller.stage_manager import StageController
from hyprplane.controller.window import WindowController, WindowStack


class CommandStrategy(ABC):
    @abstractmethod
    async def execute(self, controller: WindowController, windStack: WindowStack, args):
        pass


class ToggleCommand(CommandStrategy):
    async def execute(self, controller, windStack, args):
        arg = args[0]
        prev = windStack.getPrev()
        if arg is None:
            print("Must supply argument to toggle window")
            return

        windAddrs = await controller.getWindowAddress(arg[0])
        if prev is None:
            active = await controller.get_active_window()
            if windAddrs is None or active is None:
                print("Invalid window classname")
                return

            windStack.appendToStack(active["address"])
            await controller.focus_window(windAddrs)
        else:
            await controller.focus_window(prev)
            windStack.appendToStack(windAddrs)


class LockPinCommand(CommandStrategy):
    async def execute(self, controller, windStack, args):
        await controller.lockWindow()


class GetActionsCommand(CommandStrategy):
    async def execute(self, controller, windStack, args):
        actions = controller.get_available_actions()
        return json.dumps(actions).encode()


class PinCommand(CommandStrategy):
    async def execute(self, controller, windStack, args):
        if len(args) < 2:
            print("Must supply at least 2 windows to pin")
            return

        win1, win2 = args
        win1Addrs = await controller.getWindowAddress(win1)
        win2Addrs = await controller.getWindowAddress(win2)

        windStack.setPinLock()
        windStack.appendToStack(win1Addrs)
        windStack.appendToStack(win2Addrs)

        wIndex1 = windStack.stacks[-1]
        wIndex2 = windStack.stacks[-2]

        active = await controller.get_active_window()
        if active is None:
            return

        active = active["address"]
        prev = windStack.getPrev()
        if prev is None or active == wIndex1:
            await controller.focus_window(wIndex2)
        else:
            await controller.focus_window(wIndex1)


class LaunchPair(CommandStrategy):
    async def execute(self, controller, windStack, args):
        if len(args) < 2:
            print("Must supply at least 2 windows to pin")
            return
        for app in args:
            process = Popen([app], stdout=PIPE, stderr=PIPE)
            stdout, stderr = process.communicate()
            if stdout:
                return
            await controller.lockWindow()


class CommandResolver:
    def __init__(self):
        self._strategies = {
            "toggle": ToggleCommand(),
            "lockpin": LockPinCommand(),
            "get_actions": GetActionsCommand(),
            "toggle-lock": ToggleLockCommand(),
            "switch-group": ToggleLockGroupCommand(),
            "pin": ModifyLockGroupCommand(),
            "generate-lock": GenerateLockGroupCommand(),
            "toggle-float": ToggleFloatMode(),
            "estage": EnterStage(),
            "cycle-stage": CycleStage(),
        }

    def getStrategy(self, command):
        return self._strategies.get(command, None)


class GenerateLockGroupCommand(CommandStrategy):
    async def execute(self, controller: WindowController, windStack: WindowStack, args):
        # groupName = args[0] if args else "default"
        controller.createGroup(args[0] if args else None)


class ModifyLockGroupCommand(CommandStrategy):
    async def execute(self, controller: WindowController, windStack: WindowStack, args):
        if len(args) < 2:
            print("Must supply group name and window class.")
            return

        win = await controller.get_active_window()
        curr = controller.pinLockTable["currentGroup"]
        if win is None:
            return

        windowAddress = win["address"]
        controller.getWinFromGroup(curr)
        if windowAddress:
            controller.addWindowToGroup(curr, windowAddress)
            currentWindow = await controller.get_active_window()
            if currentWindow:
                await controller.lockWindow()


class ToggleLockCommand(CommandStrategy):
    def __init__(self, direction="forward"):
        self.direction = direction

    async def execute(self, controller: WindowController, windStack: WindowStack, args):
        dir = args[0] if args else self.direction
        await controller.toggleWithinGroup(dir)


class ToggleLockGroupCommand(CommandStrategy):
    def __init__(self, direction="forward"):
        self.direction = direction

    async def execute(self, controller: WindowController, windStack: WindowStack, args):
        dir = args[0] if args else self.direction
        await controller.toggleGroup()


class ClearGroup(CommandStrategy):
    def __init__(self, clearance="current"):
        self.clearance = clearance

    async def execute(self, controller: WindowController, windStack: WindowStack, args):
        dir = args[0] if args else self.clearance
        controller.pinLockTable["group"]
        # await controller.clearLockGroup()


class ToggleFloatMode(CommandStrategy):
    def __init__(self, clearance="current"):
        self.clearance = clearance
        self.controlMode = "layout"

    async def execute(self, controller: LayoutController, windStack: WindowStack, args):
        dir = args[0] if args else self.clearance
        print("CEN", controller)
        await controller.toggleFloatMode()


class EnterStage(CommandStrategy):
    def __init__(self, clearance="current"):
        self.clearance = clearance
        self.controlMode = "layout"

    async def execute(self, controller: StageController, windStack: WindowStack, args):
        dir = args[0] if args else self.clearance
        await controller.toggle_layout_mode()


class CycleStage(CommandStrategy):
    def __init__(self, clearance="current"):
        self.clearance = clearance
        self.controlMode = "layout"

    async def execute(self, controller: StageController, windStack: WindowStack, args):
        dir = args[0] if args else self.clearance
        await controller.cycle_main_window()
