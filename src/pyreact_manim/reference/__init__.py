"""Offline adapters for the pinned, real ManimGL reference implementation.

Importing this package does not import ManimGL or any game runtime modules.
"""

from .exporter import ExportSettings, export_text_transform

__all__ = ["ExportSettings", "export_text_transform"]
