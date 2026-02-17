import os
import sys

# Add shared folder to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "shared")))

from saas_db import get_all_clients_db


def list_and_debug_clients():
    print("--- LISTING CLIENTS ---")
    try:
        clients = get_all_clients_db()
        for c in clients:
            print(
                f"ID: {c['id']} | Name: {c['name']} | Token: {c['token']} | User: {c['username']}"
            )

        print("\n--- CHECKING DUPLICATES ---")
        seen_tokens = {}
        for c in clients:
            if c["token"] in seen_tokens:
                print(f"❌ DUPLICATE TOKEN FOUND: {c['token']}")
                print(
                    f"   Original: {seen_tokens[c['token']]['name']} ({seen_tokens[c['token']]['id']})"
                )
                print(f"   Duplicate: {c['name']} ({c['id']})")
            else:
                seen_tokens[c["token"]] = c

    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    list_and_debug_clients()
