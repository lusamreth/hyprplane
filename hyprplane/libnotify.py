import dbus


class Notification:
    """
    Displays a notification.

    Args:
        summary (str): Summary text.
        message (str): The message body (optional).
        timeout (int): Notification length in milliseconds (optional).
        app_name (str): Caller app name. Defaults to 'notify-send'.
        kwargs: Additional arguments (optional).
    """

    def __init__(
        self, summary, message="", timeout=2000, app_name="notify-send", **kwargs
    ):
        self.summary = summary
        self.message = message
        self.timeout = timeout
        self.app_name = app_name
        self.kwargs = kwargs

    def __call__(self):
        self.send_notification()

    def send_notification(self):
        bus = dbus.SessionBus()
        notify_service = bus.get_object(
            "org.freedesktop.Notifications", "/org/freedesktop/Notifications"
        )
        notify_interface = dbus.Interface(
            notify_service, "org.freedesktop.Notifications"
        )

        app_name = self.app_name
        replaces_id = 0
        app_icon = ""
        summary = self.summary
        body = self.message
        actions = dbus.Array([], signature="s")
        hints = dbus.Dictionary(self.kwargs, signature="sv")
        expire_timeout = self.timeout

        notify_interface.Notify(
            app_name,
            replaces_id,
            app_icon,
            summary,
            body,
            actions,
            hints,
            expire_timeout,
        )


def notification(summary, message="", timeout=2000, app_name="notify-send", **kwargs):
    status = Notification(summary, message, timeout, app_name, **kwargs)()
    return status


# Example usage
