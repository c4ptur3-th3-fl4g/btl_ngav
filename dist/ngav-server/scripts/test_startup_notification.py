#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from server.alert import send_startup_notification


def main() -> None:
    parser = argparse.ArgumentParser(description="Send NGAV startup notification through enabled alert channels.")
    parser.add_argument("--config", default="config/config.yaml", help="Path to NGAV config.yaml")
    args = parser.parse_args()

    results = send_startup_notification(config_path=Path(args.config))
    enabled_results = [result for result in results if result.enabled]
    if not enabled_results:
        print("[info] no alert channel is enabled")
        return

    failed = False
    for result in enabled_results:
        if result.sent:
            print(f"[ok] startup notification sent via {result.channel}")
        else:
            failed = True
            print(f"[warn] startup notification failed via {result.channel}: {result.error}")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
