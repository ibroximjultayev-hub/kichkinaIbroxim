"""JARVIS v8 Office + Instagram image approval add-on.

Existing JARVIS v8 commands and the Office/Instagram agent remain intact.
This opt-in launcher adds a two-stage Instagram approval path:
    1. approve a caption -> generate and preview a JPEG image in Telegram;
    2. approve the preview -> publish that JPEG to a public GitHub repo
       and send caption + image_url to the existing Make.com webhook.

Neither submitting the webhook nor an HTTP 2xx response proves Instagram
publication. Keep the Make scenario disabled while configuring mappings.

Environment variables already used by existing bot:
    OPENAI_API_KEY, GITHUB_TOKEN, MAKE_WEBHOOK_URL, BOT_OWNER_ID
Optional:
    INSTAGRAM_IMAGE_MODEL=gpt-image-1-mini
    GITHUB_MEDIA_REPO=ibroximjultayev-hub/kichkinaIbroxim  # MUST be public
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import os
import re
import secrets
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

from PIL import Image, ImageOps
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

import JARVIS_v8_office_instagram as office_instagram

LOG = logging.getLogger("KichkinaIbrohim.InstagramMedia")
GITHUB_API = "https://api.github.com"
GITHUB_RAW = "https://raw.githubusercontent.com"
MEDIA_BRANCH = "instagram-media"  # never trigger Railway deploys from main
DEFAULT_REPO = "ibroximjultayev-hub/kichkinaIbroxim"
MAX_JPEG_BYTES = 7_500_000
MAX_CAPTION_CHARS = 2200


def valid_repo(value: str) -> str:
    """Allow only conventional owner/repo segments; never arbitrary URLs."""
    repo = (value or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}", repo):
        raise ValueError("GITHUB_MEDIA_REPO must be owner/repo")
    owner, name = repo.split("/", 1)
    if owner in (".", "..") or name in (".", ".."):
        raise ValueError("Unsafe repository path")
    return repo


def validate_webhook(url: str) -> str:
    from urllib.parse import urlsplit
    u = urlsplit((url or "").strip())
    if (u.scheme != "https" or not u.hostname or not
            u.hostname.startswith("hook.") or
            not u.hostname.endswith(".make.com") or
            not u.path.strip("/") or u.username or u.password or u.port):
        raise ValueError("MAKE_WEBHOOK_URL is not a Make.com HTTPS webhook")
    return url


def generated_jpeg(encoded: str) -> bytes:
    """Re-encode generated image as metadata-free JPEG accepted by Meta."""
    data = base64.b64decode(encoded, validate=True)
    if len(data) > 18_000_000:
        raise ValueError("Image source is too large")
    with Image.open(io.BytesIO(data)) as src:
        src.verify()
    with Image.open(io.BytesIO(data)) as src:
        img = ImageOps.exif_transpose(src).convert("RGB")
        w, h = img.size
        if w < 320 or h < 320:
            raise ValueError("Image is smaller than 320px")
        if not 0.8 <= w / h <= 1.91:
            raise ValueError("Image aspect ratio is not supported by Instagram")
        # Image API usually produces 1024x1024; cap to Instagram's max width.
        if w > 1440:
            img.thumbnail((1440, 1440), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=85, optimize=True)
        jpeg = out.getvalue()
    if len(jpeg) > MAX_JPEG_BYTES:
        raise ValueError("JPEG is larger than Meta upload limit")
    return jpeg


async def render_instagram_jpeg(legacy: Any, caption: str) -> bytes:
    """Generate an original visual for an already approved textual draft."""
    # Keep captions out of the actual image: an Instagram caption goes below it.
    prompt = (
        "Create an original, polished, square social-media photograph or "
        "illustration that visually complements the following Uzbek/Russian "
        "Instagram caption. High-quality professional design, tasteful "
        "lighting, clear composition, no brand logos, no watermarks, "
        "no text or writing on the image. Avoid depicting a real identifiable "
        "person unless explicitly requested. Caption context: " + caption[:1500]
    )
    model = os.getenv("INSTAGRAM_IMAGE_MODEL", "gpt-image-1-mini").strip() or "gpt-image-1-mini"
    result = await asyncio.wait_for(
        legacy.AI.images.generate(model=model, prompt=prompt, size="1024x1024", n=1),
        timeout=165,
    )
    if not result.data or not getattr(result.data[0], "b64_json", None):
        raise RuntimeError("Image API did not return base64 image data")
    return await asyncio.to_thread(generated_jpeg, result.data[0].b64_json)


def _github_request(url: str, token: str, *, method="GET", payload=None) -> dict[str, Any]:
    headers = {
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "JARVIS-v8-InstagramMedia",
    }
    body = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=45) as resp:
        return json.load(resp)


def _ensure_media_branch(token: str, repo: str) -> None:
    """Only commits to a non-deployed branch; main is reserved for bot code."""
    base = f"{GITHUB_API}/repos/{repo}"
    try:
        ref = _github_request(f"{base}/git/ref/heads/{MEDIA_BRANCH}", token)
        if (ref.get("ref") or "") == f"refs/heads/{MEDIA_BRANCH}":
            return
        raise RuntimeError("Unexpected media branch reference")
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
    main = _github_request(f"{base}/git/ref/heads/main", token)
    sha = ((main.get("object") or {}).get("sha") or "").strip()
    if not re.fullmatch(r"[0-9a-fA-F]{40}", sha):
        raise RuntimeError("GitHub main commit was not found")
    try:
        _github_request(f"{base}/git/refs", token, method="POST", payload={
            "ref": f"refs/heads/{MEDIA_BRANCH}",
            "sha": sha,
        })
    except urllib.error.HTTPError as e:
        if e.code != 422:
            raise  # Race creating this ref: another worker may have created it.
        _github_request(f"{base}/git/ref/heads/{MEDIA_BRANCH}", token)


def github_upload_jpeg(jpeg: bytes, token: str, repo: str) -> str:
    """Commit JPEG to a public, non-production branch using GitHub token."""
    if not token or len(token) < 12:
        raise RuntimeError("GITHUB_TOKEN is not set")
    repo = valid_repo(repo)
    if len(jpeg) > MAX_JPEG_BYTES or not jpeg.startswith(b"\xff\xd8"):
        raise ValueError("Not a valid-sized JPEG image")
    file_name = datetime.now(timezone.utc).strftime("jarvis-%Y%m%dT%H%M%S-") + secrets.token_hex(6) + ".jpg"
    file_path = "instagram_media/" + file_name
    path = "/repos/" + repo + "/contents/" + file_path
    api_url = GITHUB_API + path
    _ensure_media_branch(token, repo)
    payload = _github_request(api_url, token, method="PUT", payload={
        "message": "Add approved Instagram image (JARVIS v8)",
        "content": base64.b64encode(jpeg).decode("ascii"),
        "branch": MEDIA_BRANCH,
    })
    sha = ((payload.get("commit") or {}).get("sha") or "").strip()
    if not re.fullmatch(r"[0-9a-fA-F]{40}", sha):
        raise RuntimeError("GitHub did not return a valid commit SHA")
    return f"{GITHUB_RAW}/{repo}/{sha}/{file_path}"


def webhook_payload(caption: str, image_url: str, telegram_id: int) -> dict[str, Any]:
    """Preserve existing Make mappings and add image_url for new mapping."""
    if len(caption.strip()) == 0 or len(caption) > MAX_CAPTION_CHARS:
        raise ValueError("Instagram caption must have 1-2200 characters")
    if not image_url.startswith("https://raw.githubusercontent.com/") or not image_url.endswith(".jpg"):
        raise ValueError("Public image URL is missing")
    return {
        "event": "instagram_post_approved",
        "caption": caption,
        "image_url": image_url,
        "telegram_user_id": int(telegram_id),
        "approved_at": datetime.now(timezone.utc).isoformat(),
    }


def approval_buttons(text: str = "✅ Расмни тасдиқлаш ва Make'га юбориш"):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(text, callback_data="ig:approve"),
        InlineKeyboardButton("❌ Бекор қилиш", callback_data="ig:reject"),
    ]])


def _preview_bytes_context(context: Any):
    data = context.user_data.get("instagram_media_preview")
    caption = context.user_data.get("instagram_draft")
    if not isinstance(data, dict) or data.get("caption") != caption:
        return None
    if not isinstance(data.get("image"), bytes):
        return None
    return data


def _clear(context: Any) -> None:
    for key in ("instagram_draft", "instagram_media_preview", "instagram_sending"):
        context.user_data.pop(key, None)


def install(legacy: Any) -> None:
    """Wrap existing JARVIS v8 Office+Instagram launcher; preserve commands."""
    office_instagram.install(legacy)
    old_post = legacy.instagram_post_command

    async def post_with_image_reset(update, context, topic=None):
        context.user_data.pop("instagram_media_preview", None)
        return await old_post(update, context, topic=topic)

    legacy.instagram_post_command = post_with_image_reset

    async def approval(update, context):
        query = update.callback_query
        await query.answer()
        if (not legacy._is_owner(update) or update.effective_chat.type != "private"):
            await query.message.reply_text("🔐 Бу амал фақат бот эгаси учун.")
            return
        if context.user_data.get("instagram_sending"):
            await query.message.reply_text("⏳ Амал бажариляпти, илтимос кутинг.")
            return
        caption = context.user_data.get("instagram_draft")
        if query.data == "ig:reject":
            _clear(context)
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text("❌ Instagram пост лойиҳаси бекор қилинди.")
            return
        if not isinstance(caption, str) or not caption.strip():
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text("Лойиҳа топилмади. Янгидан Instagram пост тайёрланг.")
            return
        if len(caption) > MAX_CAPTION_CHARS:
            await query.message.reply_text(
                "⚠️ Пост матни 2200 белгидан узун. Қисқароқ пост тайёрланг."
            )
            return

        # Confirm availability before spending credits on image generation.
        try:
            url = validate_webhook(os.getenv("MAKE_WEBHOOK_URL", ""))
            token = os.getenv("GITHUB_TOKEN", "").strip()
            if not token:
                raise ValueError("GITHUB_TOKEN missing")
            repo = valid_repo(os.getenv("GITHUB_MEDIA_REPO", DEFAULT_REPO))
        except (ValueError, RuntimeError):
            await query.message.reply_text(
                "⚠️ Railway Variables'да MAKE_WEBHOOK_URL ёки GITHUB_TOKEN текширилсин. "
                "Токенни чатга юборманг."
            )
            return

        preview = _preview_bytes_context(context)
        context.user_data["instagram_sending"] = True
        try:
            if preview is None:
                # First approval only generates preview, no external publishing.
                await query.edit_message_reply_markup(reply_markup=None)
                await query.message.reply_text(
                    "🎨 Пост расмини тайёрлаяпман. У аввал сенга кўрсатилади; "
                    "ҳали GitHub ёки Instagram'га юборилмайди."
                )
                try:
                    photo = await render_instagram_jpeg(legacy, caption)
                except Exception as exc:
                    LOG.warning("Instagram image generation failed (%s)", type(exc).__name__)
                    await query.message.reply_text(
                        "⚠️ Расм тайёрлаш муваффақиятсиз. OpenAI расм яратиш "
                        "имконияти ёки API кредити текширилсин. Қайта синаш мумкин.",
                        reply_markup=approval_buttons("🔄 Расмни қайта тайёрлаш"),
                    )
                    return
                context.user_data["instagram_media_preview"] = {
                    "caption": caption,
                    "image": photo,
                }
                image = io.BytesIO(photo)
                image.name = "JARVIS_instagram_preview.jpg"
                await query.message.reply_photo(
                    photo=image,
                    caption=("🖼 Пост учун расм тайёр. Текшириб кўр. "
                             "Фақат маъқул бўлса тасдиқла. Расм тасдиқланса "
                             "очиқ GitHub репозиторийсига жойланади ва Make.com'га юборилади."),
                    reply_markup=approval_buttons(),
                )
                return

            # Second approval may commit a PUBLIC media file and call webhook.
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text("⏳ Тасдиқланган расм ва пост матнини Make.com'га юборяпман...")
            image_url = preview.get("public_url")
            if not image_url:
                image_url = await asyncio.to_thread(github_upload_jpeg, preview["image"], token, repo)
                preview["public_url"] = image_url
            payload = webhook_payload(caption, image_url, update.effective_user.id)
            await asyncio.to_thread(legacy._send_instagram_webhook, url, payload)
            _clear(context)
            await query.message.reply_text(
                "✅ Пост матни ва JPEG расм манзили Make.com'га юборилди.\n"
                "🖼 " + image_url + "\n"
                "⚠️ Бу Instagram'да эълон қилинганини англатмайди. "
                "Сценарийда image_url майдонини расм URL'ига, "
                "caption майдонини Taglavha'га боғлаш керак."
            )
        except urllib.error.HTTPError as exc:
            LOG.warning("External media request failed (HTTP %s)", exc.code)
            await query.message.reply_text(
                "⚠️ GitHub ёки Make.com маълумотни қабул қилмади. "
                "Railway Logs'ни текширинг; қайта тасдиқлаш мумкин.",
                reply_markup=approval_buttons("🔄 Қайта юбориш"),
            )
        except Exception as exc:
            LOG.warning("Instagram media approval failed (%s)", type(exc).__name__)
            await query.message.reply_text(
                "⚠️ Расмни юбориш амалга ошмади. GitHub рухсати ва "
                "MAKE_WEBHOOK_URL созламаларини текширинг.",
                reply_markup=approval_buttons("🔄 Қайта юбориш"),
            )
        finally:
            context.user_data["instagram_sending"] = False

    legacy.instagram_approval = approval


def main() -> None:
    import bot as legacy
    install(legacy)
    legacy.main()


if __name__ == "__main__":
    main()
