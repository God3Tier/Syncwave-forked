"""Compose readiness: this container must own consumers for every required queue."""

import base64
import json
import os
import socket
import sys
from urllib.request import Request, urlopen


def check(queues: list[str]) -> None:
    credentials = f"{os.environ['AMQP_USER']}:{os.environ['AMQP_PASSWORD']}"
    authorization = "Basic " + base64.b64encode(credentials.encode()).decode()
    base_url = f"http://{os.environ['AMQP_HOST']}:15672/api"

    def get(path: str) -> list[dict]:
        request = Request(base_url + path, headers={"Authorization": authorization})
        with urlopen(request, timeout=2) as response:
            return json.load(response)

    address = socket.gethostbyname(socket.gethostname())
    worker_name = os.environ["SERVICE_NAME"] + "-worker"
    connections = {
        connection["name"]
        for connection in get("/connections")
        if connection["peer_host"] == address
        and connection.get("client_properties", {}).get("connection_name")
        == worker_name
    }
    active_queues = {
        consumer["queue"]["name"]
        for consumer in get("/consumers/%2F")
        if consumer["channel_details"]["connection_name"] in connections
    }
    missing = set(queues) - active_queues
    if missing:
        raise RuntimeError("Worker has no consumer for: " + ", ".join(sorted(missing)))


if __name__ == "__main__":
    try:
        if len(sys.argv) < 2:
            raise ValueError("Specify at least one required queue")
        check(sys.argv[1:])
    except Exception as error:
        sys.exit(str(error))
