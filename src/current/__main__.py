"""python -m current  ->  serve the app (host/port from CURRENT_HOST / CURRENT_PORT)."""
import os

import uvicorn


def main() -> None:
    uvicorn.run(
        "current.web.app:get_app",
        factory=True,
        host=os.getenv("CURRENT_HOST", "127.0.0.1"),
        port=int(os.getenv("CURRENT_PORT", "8000")),
    )


if __name__ == "__main__":
    main()
