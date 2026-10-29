"""Server operator: python -m tools.pair_station --device-id YOUR_DEVICE_ID."""

import argparse

from app import app
from auth import account_store


def main():
    parser = argparse.ArgumentParser(
        description="Issue a one-time, 15-minute station pairing code."
    )
    parser.add_argument("--device-id", required=True)
    arguments = parser.parse_args()
    with app.app_context():
        devices = app.extensions["device_tokens"].values()
        device = next((value for value in devices if str(value) == arguments.device_id), None)
        if device is None:
            parser.error("Device ID is not present in the server's authorized token mapping.")
        try:
            code = account_store().issue_pairing_code(device)
        except ValueError as error:
            parser.error(str(error))
        print("Pairing code (single use, expires in 15 minutes):", code)
        print("Give this code privately to the station owner. Do not commit it.")


if __name__ == "__main__":
    main()
