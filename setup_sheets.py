"""
One-time setup: Creates the required Google Sheets structure.
Run this after placing your credentials.json and sheet_id.txt.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.google_sheets import GoogleSheetsManager, SUMMARY_SHEET_NAME, TRANSACTIONS_SHEET_NAME


def main():
    gs = GoogleSheetsManager()
    if not gs.is_ready():
        print("ERROR: Google Sheets not configured.")
        print(f"1. Place your service account JSON key as 'credentials.json'")
        print(f"2. Paste your Google Sheet ID in 'sheet_id.txt'")
        print(f"3. Share your sheet with the service account email")
        return

    print("Authenticating...")
    gs._authenticate()
    wb = gs.client.open_by_key(gs.config.sheet_id)
    print(f"Connected to sheet: {wb.title}")

    gs._ensure_sheets_exist(wb)
    print(f"Verified sheets exist: '{SUMMARY_SHEET_NAME}' and '{TRANSACTIONS_SHEET_NAME}'")
    print("Setup complete!")


if __name__ == "__main__":
    main()
