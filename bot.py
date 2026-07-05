import os
import json
import time
import logging
import difflib
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

# 비워두면 Discord 웹훅에 직접 설정한 아이콘을 사용합니다.
# 특정 이미지로 강제하려면 Railway Variables에 DISCORD_AVATAR_URL을 넣으세요.
DISCORD_AVATAR_URL = os.getenv("DISCORD_AVATAR_URL")

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
STATE_FILE = Path(os.getenv("STATE_FILE", "state.json"))

# 첫 실행 때 기존 최근바뀜을 Discord로 보낼지 여부
# false면 첫 실행 시 현재 최신 rcid까지만 저장하고 알림은 보내지 않음
SEND_EXISTING_ON_FIRST_RUN = os.getenv("SEND_EXISTING_ON_FIRST_RUN", "false").lower() == "true"

# 실제 문서 변경 내용을 디코에 표시할지 여부
SHOW_ACTUAL_DIFF = os.getenv("SHOW_ACTUAL_DIFF", "true").lower() == "true"

# Discord embed field value는 1024자 제한이 있으므로 안전하게 900자 내외로 자릅니다.
MAX_DIFF_CHARS = int(os.getenv("MAX_DIFF_CHARS", "900"))

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
# Wiki API
# =========================

def wiki_get(params: Dict[str, str]) -> Dict[str, Any]:
    headers = {
        "User-Agent": USER_AGENT,
    }

    response = requests.get(
        WIKI_API_URL,
        params=params,
        headers=headers,
        timeout=20,
    )
    response.raise_for_status()

    data = response.json()

    if "error" in data:
        raise RuntimeError(f"MediaWiki API error: {data['error']}")

    return data


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

    data = wiki_get(params)
    return data.get("query", {}).get("recentchanges", [])


def fetch_revision_text(revid: Optional[int]) -> Optional[str]:
    if not revid:
        return None

    # MediaWiki 최신 방식: slots/main/content
    params = {
        "action": "query",
        "prop": "revisions",
        "revids": str(revid),
        "rvprop": "ids|content",
        "rvslots": "main",
        "format": "json",
        "formatversion": "2",
    }

    try:
        data = wiki_get(params)
        pages = data.get("query", {}).get("pages", [])

        if not pages:
            return None

        revisions = pages[0].get("revisions", [])
        if not revisions:
            return None

        rev = revisions[0]

        slots = rev.get("slots", {})
        main_slot = slots.get("main", {})

        if "content" in main_slot:
            return main_slot.get("content")

        if "content" in rev:
            return rev.get("content")

    except Exception as e:
        logger.warning(
            "Failed to fetch revision text with slots. revid=%s error=%s",
            revid,
            e,
        )

    # 구버전 fallback
    fallback_params = {
        "action": "query",
        "prop": "revisions",
        "revids": str(revid),
        "rvprop": "ids|content",
        "format": "json",
    }

    try:
        data = wiki_get(fallback_params)
        pages = data.get("query", {}).get("pages", {})

        for page in pages.values():
            revisions = page.get("revisions", [])
            if revisions:
                return revisions[0].get("*")

    except Exception as e:
        logger.warning(
            "Failed to fetch revision text fallback. revid=%s error=%s",
            revid,
            e,
        )

    return None


# =========================
# Formatting
# =========================

def build_page_url(title: str) -> str:
    normalized_title = title.replace(" ", "_")
    return WIKI_BASE_URL.rstrip("/") + "/" + quote(normalized_title)


def build_diff_url(old_revid: Optional[int], revid: Optional[int], page_url: str) -> str:
    if old_revid and revid:
        return f"{WIKI_BASE_URL.rstrip('/')}/Special:Diff/{old_revid}/{revid}"

    return page_url


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


def truncate_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text

    return text[:max_chars - 20].rstrip() + "\n...생략됨"


def build_actual_diff_text(old_text: Optional[str], new_text: Optional[str]) -> str:
    if new_text is None:
        return "문서 내용을 가져오지 못했습니다."

    # 새 문서인 경우: 새 본문 일부를 + 줄로 표시
    if old_text is None:
        new_lines = new_text.splitlines()

        if not new_lines:
            return "새 문서가 생성됐지만 본문 내용이 비어 있습니다."

        preview_lines = []

        for line in new_lines:
            if line.strip():
                preview_lines.append("+ " + line)

            if len("\n".join(preview_lines)) >= MAX_DIFF_CHARS:
                break

        if not preview_lines:
            return "새 문서가 생성됐지만 본문 내용이 비어 있습니다."

        return truncate_text("\n".join(preview_lines), MAX_DIFF_CHARS)

    old_lines = old_text.splitlines()
    new_lines = new_text.splitlines()

    diff_lines = list(
        difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile="이전",
            tofile="현재",
            lineterm="",
            n=2,
        )
    )

    cleaned_lines = []

    for line in diff_lines:
        # unified diff 파일 헤더 제거
        if line.startswith("--- ") or line.startswith("+++ "):
            continue

        # 너무 긴 한 줄은 자르기
        if len(line) > 220:
            line = line[:217] + "..."

        cleaned_lines.append(line)

        if len("\n".join(cleaned_lines)) >= MAX_DIFF_CHARS:
            break

    if not cleaned_lines:
        return "본문 기준 변경된 줄을 찾지 못했습니다."

    return truncate_text("\n".join(cleaned_lines), MAX_DIFF_CHARS)


def get_actual_change_text(rc: Dict[str, Any]) -> str:
    if not SHOW_ACTUAL_DIFF:
        return "실제 변경 내용 표시가 비활성화되어 있습니다."

    revid = rc.get("revid")
    old_revid = rc.get("old_revid")

    new_text = fetch_revision_text(revid)
    old_text = fetch_revision_text(old_revid) if old_revid else None

    return build_actual_diff_text(old_text, new_text)


# =========================
# Discord
# =========================

def send_discord_notification(rc: Dict[str, Any]) -> None:
    title = rc.get("title", "(제목 없음)")
    user = rc.get("user", "알 수 없음")
    comment = rc.get("comment") or "없음"
    timestamp = rc.get("timestamp", "확인 불가")
    rcid = rc.get("rcid")
    revid = rc.get("revid")
    old_revid = rc.get("old_revid")
    oldlen = rc.get("oldlen")
    newlen = rc.get("newlen")

    change_type = rc.get("type")
    change_label = get_change_type_label(rc)

    page_url = build_page_url(title)
    diff_url = build_diff_url(old_revid, revid, page_url)
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

    actual_diff_text = get_actual_change_text(rc)

    embed = {
        "title": f"{emoji} {change_label}: {title}",
        "url": page_url,
        "description": f"**편집 코멘트**\n{comment[:1000]}",
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
                "name": "시간",
                "value": str(timestamp),
                "inline": False,
            },
            {
                "name": "실제 변경 내용",
                "value": f"```diff\n{actual_diff_text}\n```",
                "inline": False,
            },
            {
                "name": "링크",
                "value": f"[문서 보기]({page_url}) / [변경 비교 보기]({diff_url})",
                "inline": False,
            },
        ],
        "footer": {
            "text": f"rcid: {rcid} / revid: {revid}",
        },
    }

    payload = {
        "username": "지금 밥위키는...",
        "embeds": [embed],
    }

    if DISCORD_AVATAR_URL:
        payload["avatar_url"] = DISCORD_AVATAR_URL

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
    logger.info("SHOW_ACTUAL_DIFF=%s", SHOW_ACTUAL_DIFF)

    while True:
        try:
            process_once()
        except Exception as e:
            logger.error("Loop error: %s", e)

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
