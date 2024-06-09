from datetime import datetime

from listentui.utilities.logger import RichLogExtended, create_logger, get_logger

__all__ = ["RichLogExtended", "create_logger", "format_time_since", "get_logger"]


def format_time_since(time: datetime, short_hand: bool = False) -> str:  # noqa: PLR0911
    now = datetime.now()
    diff = now - time

    years = diff.days // 365
    if years > 0:
        return f"{years} years ago"
    months = (diff.days % 365) // 30
    if months > 0:
        return f"{months} months ago"

    days = diff.days % 30
    hours = diff.seconds // 3600
    minutes = (diff.seconds % 3600) // 60

    if minutes == 0 and days == 0 and hours == 0:
        return "just now"

    if short_hand:
        if days > 0:
            return f"{round(days)} days ago"
        if hours > 0:
            return f"{round(hours)} hours ago"
        if minutes > 0:
            return f"{round(minutes)} minutes ago"
        return "just now"

    string: list[str] = []
    if days > 0:
        string.append(f"{round(days)} days")
    if hours > 0:
        string.append(f"{round(hours)} hours")
    if minutes > 0:
        string.append(f"{round(minutes)} minutes")
    string.append("ago")

    return " ".join(string)
