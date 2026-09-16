"""
Safe connection test — confirms your OANDA credentials work and can see
your account. This NEVER places a trade, regardless of AUTO_TRADE_ENABLED
or any other config setting; it only calls the read-only account summary
endpoint.
"""

import sys

import config
import execution


def main():
    print(f"Testing OANDA connection...")
    print(f"Environment: {config.OANDA_ENVIRONMENT}")
    print(f"Account ID:  {config.OANDA_ACCOUNT_ID or '(not set)'}")

    if not config.OANDA_API_TOKEN or not config.OANDA_ACCOUNT_ID:
        print("\n❌ OANDA_API_TOKEN and/or OANDA_ACCOUNT_ID is not set.")
        sys.exit(1)

    balance = execution.get_account_balance()

    if balance is None:
        print("\n❌ Could not fetch account balance. Check the token, "
              "account ID, and that OANDA_ENVIRONMENT matches the account "
              "type (practice vs live).")
        sys.exit(1)

    print(f"\n✅ Connected successfully. Account balance: {balance:.2f}")


if __name__ == "__main__":
    main()
