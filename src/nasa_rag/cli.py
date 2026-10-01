"""Installed command-line entry point for the NASA search application."""

from semantic_search import main as search_main


def main() -> None:
    """Run the same search CLI as ``python semantic_search.py``."""
    search_main()

if __name__ == "__main__":
    main()
