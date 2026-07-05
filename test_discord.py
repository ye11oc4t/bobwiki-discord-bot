import os
import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass


DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

if not DISCORD_WEBHOOK_URL:
    raise RuntimeError("DISCORD_WEBHOOK_URL 환경변수가 없습니다.")

payload = {
    "username": "지금 밥위키는... Test",
    "content": "✅ BoB Wiki Discord Webhook 테스트 메시지입니다.",
}

response = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=15)
response.raise_for_status()

print("Discord webhook test sent.")
