"""Locate source-checkout or installed-package data and output directories."""

from pathlib import Path

PACKAGE_DIRECTORY = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIRECTORY.parents[1]
SOURCE_CHECKOUT = (PROJECT_ROOT / "pyproject.toml").is_file()


def data_directory() -> Path:
    """Return the bundled NASA source documents."""
    return PROJECT_ROOT / "data" if SOURCE_CHECKOUT else PACKAGE_DIRECTORY / "data"


def cache_directory() -> Path:
    """Return a writable cache location for the current installation."""
    return (
        PROJECT_ROOT / "cache"
        if SOURCE_CHECKOUT
        else Path.home() / ".cache" / "nasa_rag"
    )


def cost_log_path() -> Path:
    """Return the default model cost ledger path."""
    return (
        PROJECT_ROOT / "logs" / "model_costs.jsonl"
        if SOURCE_CHECKOUT
        else Path.home() / ".local" / "state" / "nasa_rag" / "model_costs.jsonl"
    )
