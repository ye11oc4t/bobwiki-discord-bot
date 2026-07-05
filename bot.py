import os
import json
import time
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass


# =========================
# Config
# =========================

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

WIKI_API_URL = os.getenv("WIKI_API_URL", "https://kitribob.wiki/api.php")
WIKI_BASE_URL = os.getenv("WIKI_BASE_URL", "https://kitribob.wiki/wiki/")

POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "60"))
RCLIMIT = int(os.getenv("RCLIMIT", "20"))

# 0 = 일반 문서 namespace만 감시
# 전체 namespace를 보고 싶으면 빈 값으로 설정
RC_NAMESPACE = os.getenv("RC_NAMESPACE", "0")

# edit|new = 수정 + 새 문서
# new = 새 문서만
# edit = 수정만
RC_TYPE = os.getenv("RC_TYPE", "edit|new")

# Railway Volume을 붙이면 /data/state.json 추천
# Volume 없이도 동작하게 기본값은 로컬 파일로 둠
STATE_FILE = Path(os.getenv("STATE_FILE", "state.json"))

# 첫 실행 때 기존 최근바뀜을 Discord로 보낼지 여부
# false면 첫 실행 시 현재 최신 rcid까지만 저장하고 알림은 보내지 않음
SEND_EXISTING_ON_FIRST_RUN = os.getenv("SEND_EXISTING_ON_FIRST_RUN", "false").lower() == "true"

USER_AGENT = os.getenv(
    "USER_AGENT",
    "bob-wiki-discord-watcher/1.0",
)


# =========================
# Logging
# =========================

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
)

logger = logging.getLogger(__name__)


# =========================
# Validate
# =========================

def validate_config() -> None:
    if not DISCORD_WEBHOOK_URL:
        raise RuntimeError("DISCORD_WEBHOOK_URL 환경변수가 없습니다.")


# =========================
# State
# =========================

def load_state() -> Dict[str, Any]:
    if not STATE_FILE.exists():
        return {
            "initialized": False,
            "seen_rcids": [],
            "last_rcid": None,
        }

    try:
        with STATE_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning("Failed to load state file: %s", e)
        return {
            "initialized": False,
            "seen_rcids": [],
            "last_rcid": None,
        }


def save_state(state: Dict[str, Any]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

    tmp_file = STATE_FILE.with_suffix(".tmp")
    with tmp_file.open("w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    tmp_file.replace(STATE_FILE)


# =========================
# Wiki
# =========================

def fetch_recent_changes() -> List[Dict[str, Any]]:
    params = {
        "action": "query",
        "list": "recentchanges",
        "rctype": RC_TYPE,
        "rcprop": "title|timestamp|user|comment|ids|sizes|flags|loginfo",
        "rclimit": str(RCLIMIT),
        "format": "json",
    }

    if RC_NAMESPACE != "":
        params["rcnamespace"] = RC_NAMESPACE

    headers = {
        "User-Agent": USER_AGENT,
    }

    response = requests.get(
        WIKI_API_URL,
        params=params,
        headers=headers,
        timeout=15,
    )
    response.raise_for_status()

    data = response.json()

    if "error" in data:
        raise RuntimeError(f"MediaWiki API error: {data['error']}")

    return data.get("query", {}).get("recentchanges", [])


def build_page_url(title: str) -> str:
    normalized_title = title.replace(" ", "_")
    return WIKI_BASE_URL.rstrip("/") + "/" + quote(normalized_title)


def format_size_diff(oldlen: Optional[int], newlen: Optional[int]) -> str:
    if oldlen is None or newlen is None:
        return "확인 불가"

    diff = newlen - oldlen
    sign = "+" if diff >= 0 else ""
    return f"{sign}{diff} bytes"


def get_change_type_label(rc: Dict[str, Any]) -> str:
    change_type = rc.get("type")

    if change_type == "new":
        return "새 문서"
    if change_type == "edit":
        return "문서 수정"
    if change_type == "log":
        return "로그"
    if change_type == "categorize":
        return "분류 변경"

    return change_type or "변경"


# =========================
# Discord
# =========================

def send_discord_notification(rc: Dict[str, Any]) -> None:
    title = rc.get("title", "(제목 없음)")
    user = rc.get("user", "알 수 없음")
    comment = rc.get("comment") or "편집 요약 없음"
    timestamp = rc.get("timestamp", "확인 불가")
    rcid = rc.get("rcid")
    oldlen = rc.get("oldlen")
    newlen = rc.get("newlen")

    change_type = rc.get("type")
    change_label = get_change_type_label(rc)

    page_url = build_page_url(title)
    size_diff = format_size_diff(oldlen, newlen)

    if change_type == "new":
        color = 0x57F287
        emoji = "🆕"
    elif change_type == "edit":
        color = 0x5865F2
        emoji = "✏️"
    else:
        color = 0xFEE75C
        emoji = "📌"

    embed = {
        "title": f"{emoji} {change_label}: {title}",
        "url": page_url,
        "description": comment[:3500],
        "color": color,
        "fields": [
            {
                "name": "작성자",
                "value": str(user),
                "inline": True,
            },
            {
                "name": "변경량",
                "value": size_diff,
                "inline": True,
            },
            {
                "name": "rcid",
                "value": str(rcid),
                "inline": True,
            },
            {
                "name": "시간",
                "value": str(timestamp),
                "inline": False,
            },
        ],
    }

    payload = {
        "username": "지금 밥위키는...",
        "avatar_url": "https://www.mediawiki.org/static/images/project-logos/mediawikiwiki.png",
        "embeds": [embed],
    }

    response = requests.post(
        DISCORD_WEBHOOK_URL,
        json=payload,
        timeout=15,
    )

    response.raise_for_status()


# =========================
# Main loop
# =========================

def process_once() -> None:
    state = load_state()

    seen_rcids = set(state.get("seen_rcids", []))
    initialized = state.get("initialized", False)

    changes = fetch_recent_changes()

    if not changes:
        logger.info("No recent changes found.")
        return

    changes = sorted(changes, key=lambda item: item.get("rcid", 0))
    latest_rcid = max(item.get("rcid", 0) for item in changes)

    # 첫 실행 때 과거 변경사항을 우르르 보내지 않도록 방지
    if not initialized and not SEND_EXISTING_ON_FIRST_RUN:
        state["initialized"] = True
        state["last_rcid"] = latest_rcid
        state["seen_rcids"] = [item.get("rcid") for item in changes if item.get("rcid")]
        save_state(state)

        logger.info(
            "Initialized state without sending existing changes. latest_rcid=%s",
            latest_rcid,
        )
        return

    sent_count = 0

    for rc in changes:
        rcid = rc.get("rcid")

        if not rcid:
            continue

        if rcid in seen_rcids:
            continue

        try:
            send_discord_notification(rc)
            logger.info("Sent notification for rcid=%s title=%s", rcid, rc.get("title"))
            seen_rcids.add(rcid)
            sent_count += 1

            # Discord rate limit 방지용
            time.sleep(1)

        except requests.HTTPError as e:
            logger.error("Discord HTTP error for rcid=%s: %s", rcid, e)
        except Exception as e:
            logger.error("Failed to send notification for rcid=%s: %s", rcid, e)

    state["initialized"] = True
    state["last_rcid"] = latest_rcid
    state["seen_rcids"] = sorted(list(seen_rcids))[-500:]

    save_state(state)

    logger.info("Processed once. sent_count=%s latest_rcid=%s", sent_count, latest_rcid)


def main() -> None:
    validate_config()

    logger.info("BoB Wiki Discord Watcher started.")
    logger.info("WIKI_API_URL=%s", WIKI_API_URL)
    logger.info("POLL_INTERVAL=%s", POLL_INTERVAL)
    logger.info("RC_NAMESPACE=%s", RC_NAMESPACE)
    logger.info("RC_TYPE=%s", RC_TYPE)
    logger.info("STATE_FILE=%s", STATE_FILE)

    while True:
        try:
            process_once()
        except Exception as e:
            logger.error("Loop error: %s", e)

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
