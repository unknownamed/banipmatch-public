"""Private transport entry point. Only fixed status codes escape the child."""
import json
import logging
import sys

from .push import send_once


def main():
    logging.disable(logging.CRITICAL)
    try:
        data = json.loads(sys.stdin.read(32768))
        result = send_once(data)
    except Exception:
        result = {"status": "failed", "error_code": "PUSH_VALIDATION_FAILED"}
    print(json.dumps(result))


if __name__ == "__main__":
    main()
