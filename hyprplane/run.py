import asyncio
import json
import os
import traceback

SOCKET_PATH = "/tmp/hyprland_controller.sock"
TIMEOUT = 5


async def get_server_actions():
    try:
        reader, writer = await asyncio.open_unix_connection(SOCKET_PATH)
        writer.write(b"get_actions")
        await writer.drain()

        data = await asyncio.wait_for(reader.read(1024), timeout=TIMEOUT)
        print("DAATA", data)
        writer.close()
        await writer.wait_closed()

        if not data:
            return {}

        actions = json.loads(data.decode())
        if "error" in actions:
            print(f"Server returned an error: {actions['error']}")
            return {}
        return actions
    except json.JSONDecodeError as e:
        print(f"Error decoding JSON: {e}")
        return {}
    except Exception as e:
        print(f"Error communicating with server: {e}")
        traceback.print_exc()
        return {}


def get_key_input():
    while True:
        key = input("Enter the key for the keybind (e.g., d, l, g):").strip().lower()
        if key and len(key) == 1 and key.isalpha():
            return key
        print("Please enter a single alphabetic character.")


def get_action_input(actions):
    print("\nAvailable actions:")
    for i, (action, description) in enumerate(actions.items(), 1):
        print(f"{i}. {action}: {description}")

    while True:
        choice = input("\nEnter the number of the action: ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(actions):
            return list(actions.keys())[int(choice) - 1]
        print("Please enter a valid number.")


def get_args_input():
    args = input("Enter arguments for the action (press Enter if none): ").strip()
    return args.split() if args else []


def generate_keybind(key, action, args):
    args_str = " ".join(args) if args else ""
    return f"bind=SUPER,{key},exec,python3 ~/.config/hypr/winpinner/control-actions.py {action} {args_str}"


async def main():
    actions = await get_server_actions()
    if not actions:
        print("No actions available. Exiting.")
        return

    keybinds = []
    while True:
        key = get_key_input()
        action = get_action_input(actions)
        args = get_args_input()

        keybind = generate_keybind(key, action, args)
        keybinds.append(keybind)

        print(f"\nKeybind added: {keybind}")

        if input("\nDo you want to add another keybind? (y/n): ").lower() != "y":
            break

    filename = "hyprland_winpinner_keybinds.conf"
    with open(filename, "w") as f:
        for keybind in keybinds:
            f.write(keybind + "\n")

    print(f"\nKeybinds have been written to {filename}")
    print("You can now include this file in your Hyprland config with:")
    print(f"source = {os.path.abspath(filename)}")


if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    loop.run_until_complete(main())
