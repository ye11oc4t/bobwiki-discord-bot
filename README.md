# BoB Wiki Discord Bot

BoB Wiki의 최근 바뀜을 주기적으로 확인해서 새 문서나 문서 수정이 생기면 Discord Webhook으로 알림을 보내는 봇입니다.

## 기능

- MediaWiki RecentChanges API 폴링
- 새 문서 알림
- 문서 수정 알림
- Discord Embed 전송
- `rcid` 기반 중복 알림 방지
- Railway 배포 지원
- 로컬 Discord Webhook 테스트 스크립트 포함

## 구조

```text
BoB Wiki 최근바뀜
        ↓
MediaWiki API
        ↓
Python watcher
        ↓
Discord Webhook
```

## 파일 구조

```text
bob-wiki-discord-watcher/
├─ bot.py
├─ test_discord.py
├─ requirements.txt
├─ railway.json
├─ .env.example
├─ .gitignore
└─ README.md
```

## 환경변수

| 이름 | 설명 | 기본값 |
| --- | --- | --- |
| `DISCORD_WEBHOOK_URL` | Discord Webhook URL | 필수 |
| `WIKI_API_URL` | MediaWiki API URL | `https://kitribob.wiki/api.php` |
| `WIKI_BASE_URL` | Wiki 문서 URL base | `https://kitribob.wiki/wiki/` |
| `POLL_INTERVAL` | 폴링 주기 초 단위 | `60` |
| `RCLIMIT` | 한 번에 가져올 최근바뀜 개수 | `20` |
| `RC_NAMESPACE` | 감시할 namespace. `0`은 일반 문서 | `0` |
| `RC_TYPE` | `edit`, `new`, `edit|new` | `edit|new` |
| `STATE_FILE` | 중복 방지 상태 파일 경로 | `state.json` |
| `SEND_EXISTING_ON_FIRST_RUN` | 첫 실행 때 기존 최근바뀜도 전송할지 여부 | `false` |
| `USER_AGENT` | 위키 API 요청 User-Agent | `bob-wiki-discord-watcher/1.0` |

## Discord Webhook 만들기

1. Discord에서 알림을 받을 서버로 이동
2. 알림 받을 채널 우클릭
3. `채널 편집`
4. `연동`
5. `웹후크`
6. `새 웹후크`
7. 이름을 `지금 밥위키는...` 등으로 변경
8. 채널 확인
9. `웹후크 URL 복사`

복사한 URL을 `.env` 또는 Railway Variables의 `DISCORD_WEBHOOK_URL`에 넣으면 됩니다.

주의: Webhook URL은 비밀번호처럼 취급해야 합니다. GitHub에 올리지 마세요.

## 로컬 실행

```bash
git clone https://github.com/YOUR_ID/bob-wiki-discord-watcher.git
cd bob-wiki-discord-watcher

python -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt

cp .env.example .env
```

`.env` 파일에서 아래 값 수정:

```env
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/xxxxx/yyyyy
```

Webhook 테스트:

```bash
python test_discord.py
```

봇 실행:

```bash
python bot.py
```

Windows PowerShell에서는 다음처럼 실행할 수 있습니다.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
python test_discord.py
python bot.py
```

## GitHub에 올리기

```bash
git init
git add .
git commit -m "feat: add bob wiki discord watcher"
git branch -M main
git remote add origin https://github.com/YOUR_ID/bob-wiki-discord-watcher.git
git push -u origin main
```

## Railway 배포

### 1. 새 프로젝트 생성

Railway에서:

```text
New Project → Deploy from GitHub repo → bob-wiki-discord-watcher 선택
```

### 2. Variables 설정

Railway Service의 `Variables` 탭에서 최소 아래 값 추가:

```env
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/xxxxx/yyyyy
```

권장 설정:

```env
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/xxxxx/yyyyy
POLL_INTERVAL=60
RCLIMIT=20
RC_NAMESPACE=0
RC_TYPE=edit|new
SEND_EXISTING_ON_FIRST_RUN=false
```

### 3. Volume 설정 권장

중복 알림 방지 상태 파일을 영구 저장하려면 Railway Volume을 붙이는 것을 권장합니다.

Railway에서:

```text
Service → Volumes → Add Volume
Mount Path: /data
```

그 다음 Variables에 아래 값을 추가하거나 수정합니다.

```env
STATE_FILE=/data/state.json
```

Volume을 안 붙여도 동작은 하지만, 재배포 시 `state.json`이 사라질 수 있습니다. 그러면 최근 변경사항이 다시 알림으로 갈 수 있습니다.

### 4. 배포 확인

Railway의 `Deployments` 또는 `Logs`에서 아래와 비슷한 로그가 보이면 정상입니다.

```text
BoB Wiki Discord Watcher started.
Initialized state without sending existing changes.
```

그 다음부터 새 문서 작성이나 문서 수정이 생기면 Discord에 알림이 옵니다.

## 새 문서만 감시

Railway Variables에서:

```env
RC_TYPE=new
```

## 수정만 감시

```env
RC_TYPE=edit
```

## 일반 문서만 감시

```env
RC_NAMESPACE=0
```

## 모든 namespace 감시

`RC_NAMESPACE` 값을 빈 값으로 둡니다.

```env
RC_NAMESPACE=
```

## 첫 실행 때 최근바뀜도 전부 보내고 싶은 경우

기본값은 첫 실행 때 기존 최근바뀜을 보내지 않습니다.

기존 최근바뀜까지 보내려면:

```env
SEND_EXISTING_ON_FIRST_RUN=true
```

## 문제 해결

### Discord에 아무 메시지도 안 옴

먼저 로컬에서 테스트합니다.

```bash
python test_discord.py
```

테스트 메시지도 안 오면 Webhook URL이 잘못됐거나 Discord 권한 문제입니다.

### Railway에서 `DISCORD_WEBHOOK_URL 환경변수가 없습니다` 오류

Railway Variables에 `DISCORD_WEBHOOK_URL`을 추가해야 합니다.

### 재배포할 때 같은 알림이 다시 옴

Railway Volume을 붙이고 `STATE_FILE=/data/state.json`으로 설정하세요.

### 새 문서만 받고 싶음

`RC_TYPE=new`로 설정하세요.

### 너무 자주 요청하는 것 같음

`POLL_INTERVAL=120` 또는 `POLL_INTERVAL=300`으로 늘리세요.
