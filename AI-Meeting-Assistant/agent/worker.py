"""Compatibility entry point for tools expecting agent/worker.py."""

from main import entrypoint, server

__all__ = ["entrypoint", "server"]


if __name__ == "__main__":
    from livekit.agents import cli

    cli.run_app(server)
