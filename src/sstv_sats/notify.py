"""Alert channels for the ``watch`` command: console, ntfy push and generic webhooks."""

from __future__ import annotations

import json
import sys
import urllib.request

from . import __version__

UA = {"User-Agent": f"sstv-sats/{__version__}"}


class Console:
    def send(self, title: str, message: str) -> None:
        print(f"\a\n*** {title} ***\n{message}\n", flush=True)


class Ntfy:
    """Push to an ntfy topic (https://ntfy.sh or a self-hosted server) - shows up on your phone."""

    def __init__(self, topic_or_url: str):
        self.url = topic_or_url if "://" in topic_or_url else f"https://ntfy.sh/{topic_or_url}"

    def send(self, title: str, message: str) -> None:
        headers = {**UA, "Title": title.encode("ascii", "replace").decode(), "Tags": "satellite,tv", "Priority": "high"}
        req = urllib.request.Request(self.url, data=message.encode("utf-8"), headers=headers, method="POST")
        urllib.request.urlopen(req, timeout=15).close()


class Webhook:
    """POST JSON. Includes both ``content`` (Discord) and ``text`` (Slack/Mattermost/Teams-style)."""

    def __init__(self, url: str):
        self.url = url

    def send(self, title: str, message: str) -> None:
        body = json.dumps({"content": f"**{title}**\n{message}", "text": f"*{title}*\n{message}", "title": title, "message": message})
        req = urllib.request.Request(self.url, data=body.encode("utf-8"), headers={**UA, "Content-Type": "application/json"}, method="POST")
        urllib.request.urlopen(req, timeout=15).close()


def broadcast(notifiers: list, title: str, message: str) -> None:
    for n in notifiers:
        try:
            n.send(title, message)
        except Exception as exc:  # one broken channel shouldn't stop the others
            print(f"warning: {type(n).__name__} alert failed: {exc}", file=sys.stderr)
