#!/usr/bin/env python3
import asyncio
import json
import logging
import sys

SOCKET_PATH = "/tmp/hyprland_controller.sock"
TIMEOUT = 5


async def sendActionToServer(action, args):
    try:
        reader, writer = await asyncio.open_unix_connection(SOCKET_PATH)
        command = "{} {}".format(action, " ".join(args))
        writer.write(command.encode())
        await writer.drain()

        data = await asyncio.wait_for(reader.read(), timeout=TIMEOUT)
        writer.close()
        await writer.wait_closed()

        response = json.loads(data.decode())
        return response
    except Exception as e:
        print(f"Error communicating with server: {e}")
        return {"error": str(e)}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: CONTROL <action> [args...]")
        sys.exit(1)

    action = sys.argv[1]
    args = sys.argv[2:]

    loop = asyncio.new_event_loop()
    response = loop.run_until_complete(sendActionToServer(action, args))
    print(response)
