"""System tools — things the model cannot know without asking the host."""

from datetime import datetime


def register(mcp) -> None:
    @mcp.tool()
    def get_datetime() -> str:
        """Return the user's current local date, time and weekday."""
        now = datetime.now().astimezone()
        return now.strftime("%A, %d %B %Y, %I:%M %p %Z")
