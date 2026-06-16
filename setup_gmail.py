#!/usr/bin/env python3
"""
Gmail OAuth Token Setup

This script generates a gmail_token.json file for Gmail API authentication.
Run this once to authorize the ARIA system to send newsletters via Gmail.
"""

import os
import sys

try:
    # Import OAuth libraries
    from google_auth_oauthlib.flow import InstalledAppFlow
    
    SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
    creds_file = "gmail_credentials.json"
    token_file = "gmail_token.json"
    
    if not os.path.exists(creds_file):
        print(f"❌ Error: {creds_file} not found")
        print("   Please ensure gmail_credentials.json is in the current directory")
        sys.exit(1)
    
    print("📧 Gmail OAuth Authentication Setup")
    print("=" * 60)
    print()
    print("This will open a browser window for Gmail authorization.")
    print("You'll be asked to sign in and grant permission for ARIA to send emails.")
    print()
    
    # Create OAuth flow
    flow = InstalledAppFlow.from_client_secrets_file(
        creds_file,
        scopes=SCOPES
    )
    
    # Get credentials
    creds = flow.run_local_server(port=8080)
    
    # Save token
    with open(token_file, "w") as f:
        f.write(creds.to_json())
    
    print()
    print("✅ Success!")
    print(f"   Token saved to: {token_file}")
    print()
    print("🎉 Gmail API is now ready to use!")
    print("   Newsletters will be sent to: " + os.getenv("NEWSLETTER_RECIPIENT_EMAIL", "N/A"))
    
except ImportError:
    print("⚠️  Import error: Google OAuth libraries not fully available")
    print()
    print("📝 Workaround: You can still use ARIA in SIMULATION MODE")
    print("   The Publisher node will log newsletter details but won't send emails.")
    print()
    print("To enable actual Gmail sending:")
    print("  1. Run: pip3 install --user google-auth-oauthlib")
    print("  2. Then: python3 setup_gmail.py")
    
except Exception as e:
    print(f"❌ Error: {e}")
    print()
    print("If this is a browser/port error, try:")
    print("  • Ensure port 8080 is available")
    print("  • Or modify the script to use a different port")
    sys.exit(1)
