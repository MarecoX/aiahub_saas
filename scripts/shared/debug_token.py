import json
import os
import sys

# Add root to sys.path to resolve imports
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(os.path.dirname(current_dir))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from scripts.shared.saas_db import get_connection


def debug_db_token(target_token):
    print(f"🔍 DEBUG: Investigating Token: {target_token}")

    try:
        with get_connection() as conn:
            print(f"✅ DB Connection Successful: {conn.info.dbname}")
            with conn.cursor() as cur:
                # 1. Count Total Clients
                cur.execute("SELECT count(*) as c FROM clients")
                count = cur.fetchone()["c"]
                print(f"📊 Total Clients in DB: {count}")

                # 2. Check Specific Token
                cur.execute(
                    "SELECT id, name, token, tools_config FROM clients WHERE token = %s",
                    (target_token,),
                )
                row = cur.fetchone()

                if row:
                    print(f"✅ FOUND CLIENT: ID={row['id']}, Name={row['name']}")
                    print("Status: VALID")

                    config = row["tools_config"]
                    if isinstance(config, str):
                        config = json.loads(config)

                    waba = config.get("whatsapp", {}) or config.get(
                        "whatsapp_official", {}
                    )
                    print("\n📦 METADATA SAVED IN DB:")
                    print(f"   - Active: {waba.get('active')}")
                    print(f"   - WABA ID: {waba.get('waba_id')}")
                    print(f"   - Phone ID: {waba.get('phone_id')}")
                    print(
                        f"   - Token (First 10 chars): {waba.get('token', '')[:10]}..."
                    )
                else:
                    print(f"❌ TOKEN NOT FOUND IN DB!")

                    # 3. List First 5 Tokens for comparison
                    print("📋 First 5 Tokens in DB:")
                    cur.execute("SELECT name, token FROM clients LIMIT 5")
                    for r in cur.fetchall():
                        print(f"   - {r['name']}: {r['token']}")

    except Exception as e:
        print(f"💥 DB ERROR: {e}")


if __name__ == "__main__":
    # Token from user screenshot
    target_token = "159758cc-5e61-40bf-bf0c-bae0bd143ced"
    debug_db_token(target_token)
