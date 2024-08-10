import asyncio
import itertools
import json
import time

from .ipc import getEventStreamPath, getHyprCtrlPath

# EVENTS = f"{IPC_FOLDER}/.socket2.sock"
EVENTS_STREAM = getEventStreamPath()
HYPRCTL = getHyprCtrlPath()
MAX_EVENTS_RETRY = 10


async def getEventStream() -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    """Return a new event socket connection."""
    return await asyncio.open_unix_connection(EVENTS_STREAM)


async def getHyprCtlHandle() -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    """Return a new event socket connection."""
    return await asyncio.open_unix_connection(HYPRCTL)


async def getEventStreamRetry(
    max_retry: int = MAX_EVENTS_RETRY,
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter] | tuple[None, Exception]:
    """Obtain the event stream, retrying if it fails.

    If retry count is exhausted, returns (None, exception).
    """
    err_count = itertools.count()
    while True:
        attempt = next(err_count)
        try:
            return await getEventStream()
        except Exception as e:  # pylint: disable=W0718
            if attempt > max_retry:
                return None, e
            await asyncio.sleep(1)


# Function to execute hyprctl command and return the output as JSON
async def hyprctl_cmd(command, getOutput=False):
    start = time.perf_counter()
    output = None
    reader, writer = await getHyprCtlHandle()

    try:
        cmd = f"-j/{command}"
        # print("CMD", cmd)
        # result = subprocess.run(cmd, capture_output=True, text=True)
        writer.write(cmd.encode())
        await writer.drain()
        data = await reader.read()
        output = data.decode().strip()
        # print("raw", output)
        if output == "ok":
            return
        if not output:
            # print(f"No output from hyprctl command: {command}")
            return None
        if getOutput:
            return json.loads(output)
    except FileNotFoundError as e:
        print(f"File socket not found.Is hyprland running?")
        return None
    except json.JSONDecodeError as e:
        print(f"Error decoding JSON: {e} { command } {output}")
        print(f"Raw output: {output}")
        return None
    except Exception as e:
        print(f"Error running command: {e}")
        return None

    end = time.perf_counter()
    print("hyprland exec time", end - start)
