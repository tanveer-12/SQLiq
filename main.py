"""
SQLiq entry points.

python main.py          → start web server (default)
python main.py server   → start web server
python main.py chat     → launch terminal dashboard
"""
from __future__ import annotations

import sys


def _serve() -> None:
    import os
    import uvicorn
    from dotenv import load_dotenv
    load_dotenv()
    from app.api.server import create_app
    app = create_app()
    uvicorn.run(
        app,
        host=os.getenv("SQLIQ_HOST", "0.0.0.0"),
        port=int(os.getenv("SQLIQ_PORT", "8000")),
        reload=False,
    )


def _chat() -> None:
    import asyncio
    from dotenv import load_dotenv
    load_dotenv()
    from app.cli import main
    asyncio.run(main())


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "server"
    if command == "chat":
        _chat()
    else:
        _serve()