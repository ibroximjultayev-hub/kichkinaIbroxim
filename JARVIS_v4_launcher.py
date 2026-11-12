"""JARVIS v4 — owner-approved, conflict-checked GitHub -> Railway deployment.

Extends JARVIS v3 without editing existing bot.py or changing secrets.
Run in Railway: python JARVIS_v4_launcher.py

Workflow:
  1. JARVIS v3 creates a reviewed single-file branch after owner approval.
  2. v4 previews and validates the latest 'jarvis-review-...' branch.
  3. Owner explicitly confirms with a short, one-use SHA code within 10 min.
  4. v4 copies ONLY that reviewed file to main with GitHub Contents API.
  5. Railway's existing GitHub main auto-deploy may pick up that commit.

This does not call Railway API, control Chrome, execute untrusted code,
run unit tests in Railway, or prove the new deployment is healthy.
"""

import ast
import asyncio
import base64
import io
import logging
import re
import time
import urllib.parse

import JARVIS_v3_launcher as v3

LOG = logging.getLogger("KichkinaIbrohim.JARVISv4")
REPO = v3.REPO
PREFIX = f"/repos/{REPO}"
REVIEW_BRANCH = re.compile(r"^jarvis-review-[0-9]{8}-[0-9]{6}-[0-9a-f]{6}$")
SHA = re.compile(r"^[0-9a-f]{40}$")
CONFIRM_CODE = re.compile(r"^[0-9a-f]{8}$")
DEPLOY_WORDS = re.compile(r"(?i)(?:деплой|deploy|жойлаштир|развернут|опублик)")
CONFIRM_WORDS = ("тасдиқла", "тасдикла", "confirm", "подтверди")
CANCEL_WORDS = ("бекор", "отмена", "cancel")
PENDING_KEY = "jarvis_v4_production_pending"
PENDING_TTL = 10 * 60
MAX_TEXT = 40000
MAX_PATCH = 32000
# Guard common accidentally committed credentials. Not a complete secret scanner.
SECRET_PATTERNS = (
    re.compile(r"gh[pousr]_[A-Za-z0-9_]{16,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{16,}"),
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)


class DeployError(Exception):
    """Expected deployment validation error, safe to present in Telegram."""


def valid_sha(value):
    return isinstance(value, str) and bool(SHA.fullmatch(value))


def safe_branch(name):
    if not isinstance(name, str) or not REVIEW_BRANCH.fullmatch(name):
        raise DeployError("Фақат JARVIS яратган review шохобчасини қабул қиламан.")
    return name


def safe_deploy_path(path):
    """Only one ordinary code or document file, never secrets/config/dependencies."""
    try:
        path = v3.safe_file_path(path)
    except ValueError as err:
        raise DeployError("Файлни production'га ўтказиш тақиқланган.") from err
    if not path.endswith((".py", ".md", ".txt")):
        raise DeployError("Бу версия фақат .py/.md/.txt файлларни жойлаштиради.")
    if path.lower().startswith(("requirements", "procfile", "railway", "dockerfile")):
        raise DeployError("Тизим конфигурацияси JARVIS орқали ўзгартирилмайди.")
    return path


def validate_review_content(path, content):
    if not isinstance(content, str) or not content.strip() or len(content) > MAX_TEXT:
        raise DeployError("Файл жуда катта ёки бўш; қўлда текшириш керак.")
    if any(p.search(content) for p in SECRET_PATTERNS):
        raise DeployError("Файлда махфий калитга ўхшаш қатор бор. Деплой тўхтатилди.")
    if path.endswith(".py"):
        try:
            ast.parse(content, filename=path)
        except SyntaxError as exc:
            raise DeployError(f"Python синтаксис хатоси, {exc.lineno}-қатор. Деплой йўқ.") from None


def decode_file(item):
    if not isinstance(item, dict) or item.get("encoding") != "base64":
        raise DeployError("GitHub файлни матн сифатида қайтармади.")
    try:
        contents = base64.b64decode(item["content"], validate=False).decode("utf-8")
    except (KeyError, ValueError, UnicodeError):
        raise DeployError("Файл UTF-8 матн эмас.") from None
    return contents


def contents_route(path, ref):
    safe_deploy_path(path)
    if ref != "main" and not valid_sha(ref):
        raise DeployError("GitHub commit идентификатори нотўғри.")
    path = urllib.parse.quote(path, safe="/")
    return f"{PREFIX}/contents/{path}?ref={ref}"


async def current_ref(branch):
    if branch != "main":
        safe_branch(branch)
    obj = await v3.gh("GET", f"{PREFIX}/git/ref/heads/{branch}")
    val = obj.get("object", {}).get("sha")
    if not valid_sha(val):
        raise DeployError("GitHub шохобча SHA қиймати нотўғри.")
    return val


async def latest_review_branch():
    result = await v3.gh("GET", f"{PREFIX}/branches?per_page=100")
    if not isinstance(result, list):
        raise DeployError("GitHub шохобчаларини ўқий олмадим.")
    branches = sorted((x.get("name", "") for x in result if isinstance(x, dict)
                       and REVIEW_BRANCH.fullmatch(str(x.get("name", "")))), reverse=True)
    if not branches:
        raise DeployError("JARVIS review шохобчаси топилмади.")
    return branches[0]


async def review_snapshot(branch):
    """A single reviewed commit, one changed file, unchanged since its base on main."""
    safe_branch(branch)
    branch_head, main_head = await asyncio.gather(current_ref(branch), current_ref("main"))
    commit = await v3.gh("GET", f"{PREFIX}/commits/{branch_head}")
    parents = commit.get("parents", [])
    if len(parents) != 1 or not valid_sha(parents[0].get("sha")):
        raise DeployError("Шохобчада битта оддий commit бўлиши керак.")
    base_sha = parents[0]["sha"]
    if base_sha == main_head:
        pass  # Fast forward also allowed, but use the same file-copy workflow.
    comparison = await v3.gh("GET", f"{PREFIX}/compare/{base_sha}...{branch_head}")
    files = comparison.get("files")
    if comparison.get("ahead_by") != 1 or comparison.get("behind_by") != 0:
        raise DeployError("Шохобчада кутилмаган қўшимча commit бор.")
    if not isinstance(files, list) or len(files) != 1 or files[0].get("status") != "modified":
        raise DeployError("Фақат битта мавжуд файлнинг ўзгаришига рухсат.")
    path = safe_deploy_path(files[0].get("filename", ""))
    patch = files[0].get("patch")
    if not isinstance(patch, str) or not patch.strip() or len(patch) > MAX_PATCH:
        raise DeployError("Ўзгариш фарқини тўлиқ текшириб бўлмади.")

    old, reviewed, main = await asyncio.gather(
        v3.gh("GET", contents_route(path, base_sha)),
        v3.gh("GET", contents_route(path, branch_head)),
        v3.gh("GET", contents_route(path, "main")),
    )
    old_content = decode_file(old)
    reviewed_content = decode_file(reviewed)
    main_content = decode_file(main)
    if old_content != main_content:
        raise DeployError("main'да шу файл review'дан кейин ўзгарган. Деплой қилмадим.")
    if reviewed_content == old_content:
        raise DeployError("Файлда ҳақиқий ўзгариш йўқ.")
    validate_review_content(path, reviewed_content)
    if len(patch.encode("utf-8")) > MAX_PATCH:
        raise DeployError("Файл фарқи юбориш учун жуда катта.")
    return {
        "branch": branch, "head": branch_head, "main_head": main_head,
        "path": path, "file_sha": main.get("sha"), "text": reviewed_content,
        "patch": patch, "base_sha": base_sha,
    }


async def preview(update, context, branch=None):
    msg = update.effective_message
    context.user_data.pop(PENDING_KEY, None)
    branch = safe_branch(branch) if branch else await latest_review_branch()
    await msg.reply_text("🔍 Review шохобчасини ва main билан фарқини текширяпман...")
    snapshot = await review_snapshot(branch)
    if not isinstance(snapshot["file_sha"], str):
        raise DeployError("GitHub файл SHA жавоби нотўғри.")
    code = snapshot["head"][:8]
    context.user_data[PENDING_KEY] = {
        "branch": branch, "head": snapshot["head"], "main_head": snapshot["main_head"],
        "path": snapshot["path"], "file_sha": snapshot["file_sha"],
        "created": time.monotonic(), "code": code,
    }
    ext = snapshot["path"].rsplit(".", 1)[-1].lower()
    caution = ("⚠️ Бу Python коди. Фақат синтаксис текширилди, функциялар ва Railway ишлаши тест қилинмади.\n"
               if ext == "py" else "✅ Матнли ҳужжат учун фарқ текширилди.\n")
    await msg.reply_text(
        "📦 JARVIS v4 — production'га чиқаришдан ОЛДИНГИ текширув\n"
        f"Шохобча: {branch}\nФайл: {snapshot['path']}\n"
        f"Review commit: {code}\n"
        f"Ҳозирги main: {snapshot['main_head'][:8]}\n"
        "Бир файл ўзгарган, main'да шу файл ҳали ўзгармаган.\n"
        + caution +
        "Railway GitHub main уланиши ишласа, main янгиланиши деплойни бошлайди.\n\n"
        f"10 дақиқа ичида қабул қилиш: Жарвис, GitHub деплой тасдиқла {code}\n"
        "Бекор қилиш: Жарвис, GitHub деплой бекор қил\n"
        "⚠️ Тасдиқсиз production ўзгармайди."
    )
    await msg.reply_document(document=io.BytesIO(snapshot["patch"].encode("utf-8")),
                             filename="JARVIS_production.diff",
                             caption="Ишлаб турган версияга киритиладиган аниқ фарқ")


async def confirm(update, context, user_code):
    msg = update.effective_message
    staged = context.user_data.get(PENDING_KEY)
    if not staged or time.monotonic() - staged["created"] > PENDING_TTL:
        context.user_data.pop(PENDING_KEY, None)
        await msg.reply_text("⚠️ Деплой тасдиғи мавжуд эмас ёки 10 дақиқа ўтди. Қайта текшир.")
        return
    if not CONFIRM_CODE.fullmatch(user_code or "") or user_code != staged["code"]:
        await msg.reply_text("⚠️ Тасдиқ коди нотўғри. Деплой қилинмади.")
        return
    # Redeploy preview must still match both branch and main. No shell/runtime execution.
    latest = await review_snapshot(staged["branch"])
    if (latest["head"] != staged["head"] or latest["main_head"] != staged["main_head"]
        or latest["file_sha"] != staged["file_sha"] or latest["path"] != staged["path"]):
        context.user_data.pop(PENDING_KEY, None)
        await msg.reply_text("⚠️ main ёки review ўзгарган. Хавфсизлик учун тасдиқ бекор қилинди; қайта текшир.")
        return

    # One-use confirmation: remove the pending action BEFORE the write.
    context.user_data.pop(PENDING_KEY, None)
    result = await v3.gh("PUT", f"{PREFIX}/contents/{urllib.parse.quote(latest['path'], safe='/')}", {
        "message": "JARVIS v4 approved deploy: " + latest["path"],
        "content": base64.b64encode(latest["text"].encode("utf-8")).decode("ascii"),
        "sha": latest["file_sha"],
        "branch": "main",
    })
    commit_sha = str(result.get("commit", {}).get("sha", ""))
    if not valid_sha(commit_sha):
        await msg.reply_text("⚠️ GitHub'га ёзув жавоби ноаниқ. main'ни қўлда текшир; қайта босма.")
        return
    await msg.reply_text(
        "✅ GitHub main янгиланди.\n"
        f"Файл: {latest['path']}\nCommit: {commit_sha[:9]}\n"
        f"https://github.com/{REPO}/commit/{commit_sha}\n\n"
        "Railway main'га уланган бўлса, автоматик деплой бошланиши мумкин. "
        "Бу хабар Railway ACTIVE эканини тасдиқламайди; Deployments ва Logs'ни текшир."
    )


def parse_branch_request(text):
    match = re.search(r"jarvis-review-[0-9]{8}-[0-9]{6}-[0-9a-f]{6}", text)
    return match.group(0) if match else None


async def handle_deploy(legacy, update, context, text):
    msg = update.effective_message
    if update.effective_chat.type != "private" or not legacy._is_owner(update):
        await msg.reply_text("🔐 Деплой фақат бот эгасининг шахсий Telegram чатида.")
        return
    lowered = text.lower()
    try:
        if v3._has(lowered, CANCEL_WORDS):
            context.user_data.pop(PENDING_KEY, None)
            await msg.reply_text("✅ Деплой лойиҳаси бекор қилинди. main ўзгармади.")
        elif v3._has(lowered, CONFIRM_WORDS):
            match = re.search(r"\b([0-9a-f]{8})\b", lowered)
            await confirm(update, context, match.group(1) if match else "")
        else:
            await preview(update, context, parse_branch_request(text))
    except (DeployError, v3.GitHubError, asyncio.TimeoutError) as err:
        # Known errors must be safe to display and must not include secrets.
        await msg.reply_text("⚠️ " + ("GitHub жавоби кечикди." if isinstance(err, asyncio.TimeoutError) else str(err)))
    except Exception as err:
        # Never print request headers or exception contents; may include token.
        LOG.error("v4 deploy failed unexpectedly: %s", type(err).__name__)
        await msg.reply_text("⚠️ GitHub операциясида хато. main'ни ва Railway Logs'ни текшир.")


def install(legacy):
    v3.install(legacy)
    old_dispatch = legacy.dispatch_user_text

    async def v4_dispatch(update, context, text):
        cleaned = v3.v2.strip_wake_word(text)
        if (cleaned is not None and v3.GH_WORD.search(cleaned)
                and DEPLOY_WORDS.search(cleaned)):
            await handle_deploy(legacy, update, context, cleaned)
        else:
            await old_dispatch(update, context, text)

    legacy.dispatch_user_text = v4_dispatch


def main():
    import bot as legacy
    logging.getLogger("httpx").setLevel(logging.WARNING)
    install(legacy)
    legacy.main()


if __name__ == "__main__":
    main()
