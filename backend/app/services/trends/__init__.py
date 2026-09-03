"""Trend Intelligence for 動画制作エージェント Kairo.

`collector` fetches and stores, `worker` schedules it, `store` queries it,
`genre` organises it, and `service` is what the production pipeline talks
to. Importing this package pulls in nothing heavy and starts nothing - the
worker is started explicitly from application startup.
"""
from app.services.trends import collector, genre, service, sources, store, worker

__all__ = ["collector", "genre", "service", "sources", "store", "worker"]
