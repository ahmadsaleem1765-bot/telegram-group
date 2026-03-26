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
import traceback
from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError

# Load .env file
print("[1/8] Loading .env file...")
load_dotenv()
print("      .env loaded OK")

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
    print(f"\n[2/8] Checking credentials...")
    if not API_ID or not API_HASH:
        print("ERROR: Please set API_ID and API_HASH environment variables")
        print("Get them from https://my.telegram.org/apps")
        return

    if not API_ID.isdigit():
        print("ERROR: API_ID must be a numeric value")
        print("Get it from https://my.telegram.org/apps")
        return

    print(f"      API_ID  = {API_ID}")
    print(f"      API_HASH = {API_HASH[:6]}...{API_HASH[-4:]} (masked)")

    print("=" * 50)
    print("Telegram Session String Generator")
    print("=" * 50)

    # Build proxy settings if configured
    proxy = None
    print(f"\n[3/8] Checking proxy settings...")
    if PROXY_TYPE and PROXY_HOST and PROXY_PORT:
        try:
            import socks
            proxy_types = {'socks5': socks.SOCKS5, 'socks4': socks.SOCKS4, 'http': socks.HTTP}
            ptype = proxy_types.get(PROXY_TYPE.lower())
            if ptype:
                proxy = (ptype, PROXY_HOST, int(PROXY_PORT))
                print(f"      Proxy configured: {PROXY_TYPE}://{PROXY_HOST}:{PROXY_PORT}")
            else:
                print(f"WARNING: Unknown proxy type '{PROXY_TYPE}', connecting without proxy")
        except ImportError:
            print("WARNING: pysocks not installed. Run: pip install pysocks")
            print("         Connecting without proxy...")
    else:
        print("      No proxy configured (set PROXY_TYPE/HOST/PORT in .env if needed)")

    print(f"\n[4/8] Creating Telegram client...")
    client = TelegramClient(SESSION_NAME, int(API_ID), API_HASH, proxy=proxy)
    print("      Client created OK")

    print(f"\n[5/8] Connecting to Telegram servers...")
    print("      (This is where network errors appear — needs internet access to Telegram)")
    try:
        await client.connect()
        print("      Connected OK")
    except Exception as e:
        print(f"\nERROR connecting to Telegram: {e}")
        print("\nFull traceback:")
        traceback.print_exc()
        print("\nPossible fixes:")
        print("  - Turn on a VPN (Telegram may be blocked in your region)")
        print("  - Set PROXY_TYPE/PROXY_HOST/PROXY_PORT in your .env")
        print("  - Check your internet connection")
        return

    print(f"\n[6/8] Checking if already authorized...")
    try:
        if await client.is_user_authorized():
            print("      Already authorized!")
            session_string = client.session.save()
            print(f"\nYour session string:\n\n{session_string}\n")
            print("Copy this string and use it in your application!")
            await client.disconnect()
            return
        print("      Not yet authorized — proceeding with login")
    except Exception as e:
        print(f"ERROR checking authorization: {e}")
        traceback.print_exc()
        await client.disconnect()
        return

    phone = input("\nEnter your phone number (with country code, e.g., +8612345678900): ")

    print(f"\n[7/8] Sending verification code to {phone}...")
    try:
        sent_code = await client.send_code_request(phone)

        # Show exactly where Telegram sent the code
        code_type = type(sent_code.type).__name__
        print(f"\n      >>> Code type received: {code_type}")
        if "App" in code_type:
            print("      >>> WHERE TO LOOK: Open Telegram app → find chat named 'Telegram' (official, blue checkmark)")
            print("      >>> The code is a message inside that chat")
        elif "Sms" in code_type:
            print("      >>> WHERE TO LOOK: Check your SMS/text messages on your phone")
        elif "Call" in code_type:
            print("      >>> WHERE TO LOOK: Answer your phone — Telegram will call you with the code")
        elif "FlashCall" in code_type:
            print("      >>> WHERE TO LOOK: Telegram will call you and hang up — the code is the last digits of the number")
        else:
            print(f"      >>> Unknown delivery method. Full type info: {sent_code.type}")

        print(f"\n      Full sent_code info: {sent_code}")
    except Exception as e:
        print(f"\nERROR sending code: {e}")
        traceback.print_exc()
        await client.disconnect()
        return

    code = input("\nEnter the verification code: ")

    print(f"\n[8/8] Verifying code...")
    try:
        try:
            await client.sign_in(phone, code, phone_code_hash=sent_code.phone_code_hash)
            print("      Code accepted!")
        except SessionPasswordNeededError:
            print("      2FA password required")
            password = input("Enter your 2FA password: ")
            await client.sign_in(password=password)
            print("      2FA accepted!")
        except PhoneCodeInvalidError:
            print("\nERROR: Invalid verification code. Please try again.")
            await client.disconnect()
            return

        session_string = client.session.save()

        print("\n" + "=" * 50)
        print("SUCCESS!")
        print("=" * 50)
        print("\nYour session string:\n")
        print(session_string)
        print("\n" + "=" * 50)
        print("\nIMPORTANT:")
        print("- Copy this string and save it securely")
        print("- Add it to your .env file as: SESSION_STRING=<string>")
        print("- Keep it secret - anyone with this can access your account")
        print("=" * 50)

    except Exception as e:
        print(f"\nERROR during sign-in: {e}")
        traceback.print_exc()

    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
