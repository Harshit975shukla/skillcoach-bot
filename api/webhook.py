"""Vercel Flask entry point; all handlers share the private domain service."""

from skillcoach.web import create_app

app = create_app()
