import asyncio
import time

HOST = "127.0.0.1"
PORT = 4441

SOCKET_PATH = "/tmp/asyncio_unix_socket.sock"


async def handleEcho(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    s = time.time()
    buf = await reader.read(1024)
    msg = None
    msg = buf.decode()
    e = time.time()
    print(msg, (e - s) * 1000)
    # writer.write(b"ping back")
    # await writer.drain()
    # await asyncio.sleep(1)

    # writer.close()
    # await writer.wait_closed()


async def run_server():
    server = await asyncio.start_unix_server(handleEcho, SOCKET_PATH)
    async with server:
        await server.serve_forever()
    pass


if __name__ == "__main__":
    eventLoop = asyncio.new_event_loop()
    eventLoop.run_until_complete(run_server())
