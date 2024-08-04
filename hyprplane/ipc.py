import functools
import os

MAX_SOCKET_FILE_LEN = 15
MAX_SOCKET_PATH_LEN = 107
HYPRLAND_INSTANCE_SIGNATURE = os.environ.get(
    "HYPRLAND_INSTANCE_SIGNATURE", "NO_INSTANCE"
)
HYPRCTL_SOCK = "$XDG_RUNTIME_DIR/hypr/$HYPRLAND_INSTANCE_SIGNATURE/.socket2.sock"
SOCKET_PATH_PREFIX = "/tmp/eva-controller"


# @credit: pyprland implementation
@functools.lru_cache
def getIpcSocketPath():
    try:
        # May throw an OSError because AF_UNIX path is too long: try to work around it only if needed
        hyprIpc = (
            f'{os.environ["XDG_RUNTIME_DIR"]}/hypr/{HYPRLAND_INSTANCE_SIGNATURE}'
            if os.path.exists(
                f'{os.environ["XDG_RUNTIME_DIR"]}/hypr/{HYPRLAND_INSTANCE_SIGNATURE}'
            )
            else f"/tmp/hypr/{HYPRLAND_INSTANCE_SIGNATURE}"  # noqa: S108
        )

        if len(hyprIpc) >= MAX_SOCKET_PATH_LEN - MAX_SOCKET_FILE_LEN:
            IPC_FOLDER = f"/tmp/.{SOCKET_PATH_PREFIX}-{HYPRLAND_INSTANCE_SIGNATURE}"  # noqa: S108
            # make a link from short path to original path
            if not os.path.exists(IPC_FOLDER):
                os.symlink(hyprIpc, IPC_FOLDER)
        else:
            IPC_FOLDER = hyprIpc

    except KeyError:
        print(
            "This is a fatal error, assuming we are running documentation generation or testing in a sandbox, hence ignoring it"
        )
        IPC_FOLDER = "/"

    return IPC_FOLDER


@functools.lru_cache
def getEventStreamPath():
    return f"{getIpcSocketPath()}/.socket2.sock"


@functools.lru_cache
def getHyprCtrlPath():
    return f"{getIpcSocketPath()}/.socket.sock"
