import asyncio
import threading
from concurrent.futures.thread import ThreadPoolExecutor

from hyprplane.commander import CommandResolver
from hyprplane.constants import SOCKET_PATH
from hyprplane.controller.layout import LayoutController
from hyprplane.controller.stage_manager import StageController
from hyprplane.controller.window import WindowController, WindowStack, timeIt
from hyprplane.libnotify import notification
from hyprplane.logger import SystemLogger

sysLogger = SystemLogger.getLogger(".ipc-log.json", ".")


@timeIt
async def resolveCommand(
    controller: WindowController,
    windStack: WindowStack,
    layoutController: LayoutController,
    cmd_info: tuple,
):
    command, args = cmd_info

    resolver = CommandResolver()
    strategy = resolver.getStrategy(command)
    controlMode = getattr(strategy, "controlMode", "window")
    sysLogger.debug("strat", strategy, controlMode)
    if strategy:
        if controlMode == "layout":
            result = await strategy.execute(layoutController, windStack, args)
            sysLogger.debug(f"LayoutController ControlMode Detected {controlMode}")
            if result:
                return result
        else:
            result = await strategy.execute(controller, windStack, args)
            if result:
                return result
    else:
        sysLogger.debug(f"Unknown command: {command}")


def buildController(windowstack, windCont, layoutController):
    sysLogger.debug("Building controller...")

    async def control(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        data = await reader.read(1024)
        msg = data.decode().strip()
        sysLogger.debug(f"Received message: {msg}")
        command_parts = msg.split(maxsplit=1)
        command = command_parts[0]
        args = command_parts[1:] if len(command_parts) > 1 else []
        result = await resolveCommand(
            windCont, windowstack, layoutController, (command, args)
        )

        if result:
            writer.write(result)
            await writer.drain()

    return control


async def startController():
    sysLogger.debug("starting controller...")
    windowstack = WindowStack()
    windCont = WindowController()
    mainLoopEvent = threading.Event()
    layoutCont = StageController(windCont)
    layoutCont.setEvent(mainLoopEvent)

    # this one is dodo
    await layoutCont.start()
    cont = buildController(windowstack, windCont, layoutCont)

    server = await asyncio.start_unix_server(cont, SOCKET_PATH)
    threading.Thread(target=layoutCont._run_executor_loop).start()

    async with server:
        sysLogger.debug("server stacking", server)
        await server.serve_forever()


def main():
    eventLoop = asyncio.new_event_loop()
    eventLoop.run_until_complete(startController())


if __name__ == "__main__":
    eventLoop = asyncio.new_event_loop()
    eventLoop.run_until_complete(startController())
