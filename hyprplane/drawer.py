import math
import shutil


def isOverlapping(x1, y1, w1, h1, x2, y2, w2, h2):
    return x1 < x2 + w2 and x1 + w1 > x2 and y1 < y2 + h2 and y1 + h1 > y2


def improvedScale(value, maxValue, targetSize):
    return max(1, int((value / maxValue) * targetSize))


def calculateZIndex(windowInfo):
    baseZIndex = 0 if windowInfo["floating"] else -1000
    return baseZIndex - windowInfo["focusHistoryId"]


def drawWindow(grid, x, y, w, h, info, mode, zIndex):
    for i in range(x, x + w):
        for j in range(y, y + h):
            if i in (x, x + w - 1) or j in (y, y + h - 1):
                grid[j][i] = ("|" if i in (x, x + w - 1) else "=", zIndex)
            elif mode == "filled":
                grid[j][i] = ("-", zIndex)
            elif grid[j][i][1] < zIndex:
                grid[j][i] = (" ", zIndex)

        if w > len(info) + 2 and h > 2:
            centerX, centerY = x + w // 2 - len(info) // 2, y + h // 2
            for k, char in enumerate(info):
                grid[centerY][centerX + k] = (char, zIndex)
        else:
            grid[y][x] = (">", zIndex)


def adjustGridPosition(grid, renderPosition, maxWidth):
    if renderPosition == "center":
        leftPadding = (len(grid[0]) - maxWidth) // 2
        return [
            [(" ", -float("inf"))] * leftPadding + row[leftPadding:] for row in grid
        ]
    elif renderPosition == "right":
        return [[(" ", -float("inf"))] + row[1:] for row in grid]
    return grid


async def printWindowLayout(
    layoutController, workspaceId, renderPosition="center", mode="filled"
):
    neighbors = await layoutController.findNeighbors(workspaceId)

    if (
        not layoutController.layoutHistory
        or workspaceId not in layoutController.layoutHistory
    ):
        print("No clients in the workspace.")
        return

    windowCoords = {
        client["address"]: {
            "coords": client["at"] + client["size"],
            "floating": client.get("floating", False),
            "focusHistoryId": client.get("focusHistoryId", float("inf")),
        }
        for client in layoutController.layoutHistory.get(workspaceId, [])
    }
    for client in layoutController.layoutHistory[workspaceId]:
        windowCoords[client["address"]] = {
            "coords": client["at"] + client["size"],
            "floating": client.get("floating", False),
            "focusHistoryId": client.get("focusHistoryId", float("inf")),
        }

    if not windowCoords:
        print("No clients in the workspace.")
        return

    termWidth, termHeight = shutil.get_terminal_size()
    gridWidth, gridHeight = termWidth - 1, termHeight - 5
    maxX = max(
        x + w for x, y, w, h in [window["coords"] for window in windowCoords.values()]
    )
    maxY = max(
        y + h for x, y, w, h in [window["coords"] for window in windowCoords.values()]
    )

    grid = [[(" ", -float("inf")) for _ in range(gridWidth)] for _ in range(gridHeight)]
    normalizedCoords = []

    sortedWindows = sorted(windowCoords.items(), key=lambda x: calculateZIndex(x[1]))

    for address, windowInfo in sortedWindows:
        x, y, w, h = windowInfo["coords"]
        normX, normY = improvedScale(x, maxX, gridWidth), improvedScale(
            y, maxY, gridHeight
        )
        normWidth, normHeight = improvedScale(w, maxX, gridWidth), improvedScale(
            h, maxY, gridHeight
        )
        normalizedCoords.append((address, (normX, normY, normWidth, normHeight)))

        info = f"{w}x{h} {address[:10]}"
        zIndex = calculateZIndex(windowInfo)
        drawWindow(grid, normX, normY, normWidth, normHeight, info, mode, zIndex)

    grid = adjustGridPosition(
        grid, renderPosition, max(coord[2] for _, coord in normalizedCoords)
    )

    for row in grid:
        print("".join(char for char, _ in row))

    print("\nNormalized Coordinates:")
    for address, coords in normalizedCoords:
        print(f"Window {address}: {coords}")

    neighbors = await layoutController.findNeighbors(workspaceId)
    for address, adjacency in neighbors.items():
        print(f"\nWindow {address}:")
        for direction, neighbor in zip(
            ["top", "right", "bottom", "left"], adjacency.values()
        ):
            print(f"  {direction.capitalize()}: {neighbor if neighbor else 'None'}")
