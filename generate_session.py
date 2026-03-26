#!/usr/bin/env python3
"""
Session String Generator

This script helps generate a Telegram session string for authentication.
Run this locally (not on Railway) to generate your session string.

Usage:
    python generate_session.py

Requirements:
    - Set API_ID and API_HASH environment variables
    - Or edit the values below
"""

import os
import asyncio
from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError

# Load .env file
load_dotenv()

# Configuration - Edit these or set environment variables
API_ID = os.getenv("API_ID", "")
API_HASH = os.getenv("API_HASH", "")

# Proxy configuration (set these if Telegram is blocked in your region)
# Supported types: 'socks5', 'socks4', 'http'
PROXY_TYPE = os.getenv("PROXY_TYPE", "")   # e.g. socks5
PROXY_HOST = os.getenv("PROXY_HOST", "")   # e.g. 127.0.0.1
PROXY_PORT = os.getenv("PROXY_PORT", "")   # e.g. 1080

SESSION_NAME = "telegram_automation"


async def main():
    if not API_ID or not API_HASH:
        print("ERROR: Please set API_ID and API_HASH environment variables")
        print("Get them from https://my.telegram.org/apps")
        return

    # Validate API_ID is numeric
    if not API_ID.isdigit():
        print("ERROR: API_ID must be a numeric value")
        print("Get it from https://my.telegram.org/apps")
        return

    print("=" * 50)
    print("Telegram Session String Generator")
    print("=" * 50)

    # Build proxy settings if configured
    proxy = None
    if PROXY_TYPE and PROXY_HOST and PROXY_PORT:
        import socks
        proxy_types = {'socks5': socks.SOCKS5, 'socks4': socks.SOCKS4, 'http': socks.HTTP}
        ptype = proxy_types.get(PROXY_TYPE.lower())
        if ptype:
            proxy = (ptype, PROXY_HOST, int(PROXY_PORT))
            print(f"Using proxy: {PROXY_TYPE}://{PROXY_HOST}:{PROXY_PORT}")
        else:
            print(f"WARNING: Unknown proxy type '{PROXY_TYPE}', connecting without proxy")

    # Create client
    client = TelegramClient(SESSION_NAME, int(API_ID), API_HASH, proxy=proxy)

    await client.connect()

    # Check if already authorized
    if await client.is_user_authorized():
        print("\nAlready authorized!")
        session_string = client.session.save()
        print(f"\nYour session string:\n\n{session_string}\n")
        print("Copy this string and use it in your application!")
        await client.disconnect()
        return

    # Get phone number
    phone = input("\nEnter your phone number (with country code, e.g., +1234567890): ")

    try:
        # Send code request
        sent_code = await client.send_code_request(phone)
        print(f"\nCode sent to {phone}")

        # Get the verification code
        code = input("Enter the verification code: ")

        # Try to sign in
        try:
            await client.sign_in(phone, code, phone_code_hash=sent_code.phone_code_hash)
        except SessionPasswordNeededError:
            # Two-factor authentication
            password = input("Enter your password (2FA): ")
            await client.sign_in(password=password)

        # Get session string
        session_string = client.session.save()

        print("\n" + "=" * 50)
        print("SUCCESS!")
        print("=" * 50)
        print("\nYour session string:\n")
        print(session_string)
        print("\n" + "=" * 50)
        print("\nIMPORTANT:")
        print("- Copy this string and save it securely")
        print("- You'll need it to authenticate with Telegram")
        print("- Keep it secret - anyone with this can access your account")
        print("- If using Railway, set it as SESSION_STRING variable")
        print("=" * 50)

    except PhoneCodeInvalidError:
        print("\nERROR: Invalid verification code. Please try again.")
    except Exception as e:
        print(f"\nERROR: {e}")

    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
