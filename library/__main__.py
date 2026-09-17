"""python -m library"""

from library.app import DEFAULT_PORT, serve_forever


if __name__ == "__main__":
    serve_forever(port=DEFAULT_PORT)
