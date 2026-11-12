"""JARVIS v7 — owner-only, public-site Chromium navigator.

This is a cautious *first* interactive-browser milestone:
- Open public HTTPS pages, including JavaScript-rendered pages.
- Follow numbered same-domain links, find text, list links, take screenshots.
- No logins, cookies persistence, data entry, form submission, file downloading,
  payments, clicks on arbitrary buttons, or phone Chrome control.

Requires existing v6 -> v5 -> v4 -> v3 -> v2 -> bot.py, plus Playwright and
Chromium headless shell (see requirements-v7.txt and Dockerfile.v7).
Telegram private-owner-only. No new API tokens needed.

Railway start command: python JARVIS_v7_launcher.py
"""

import asyncio
import importlib.util
import io
import logging
import re
import time
import urllib.parse

import JARVIS_v6_launcher as v6

LOG = logging.getLogger("KichkinaIbrohim.JARVISv7")
MAX_PAGE_TEXT = 3100
MAX_LINKS = 15
IDLE_SECONDS = 8 * 60
URL_RE = re.compile(r"https://[^\s<>\"'«»]+", re.I)
OPEN_RE = re.compile(r"(?i)(?:\bоч\b|\bочиб\b|\bopen\b|\bоткрой\b|\bкир\b|\bзайди\b)")
LINKS_RE = re.compile(r"(?i)(?:ҳавола|хавола|ссылка|links?|линк)")
FIND_RE = re.compile(r"(?i)(?:қидир|изла|найди|find|поиск)")
SHOT_RE = re.compile(r"(?i)(?:скриншот|screenshot|расмини|сурат|снимок)")
CLOSE_RE = re.compile(r"(?i)(?:\bёп\b|\bйоп\b|\bзакрой\b|\bclose\b|\bтўхтат\b)")
NUMBER_RE = re.compile(r"(?<!\d)(\d{1,2})(?!\d)")


class BrowserError(Exception):
    pass


def user_command(message):
    """Only owner-addressed browser commands are intercepted."""
    raw = v6.v5.v3.v2.strip_wake_word(message or "")
    if raw is None:
        return None
    if v6.WEB_WORDS.search(raw) or (v6.extract_url(raw) and OPEN_RE.search(raw)):
        return raw.strip()
    return None


def plain_url(url):
    """Never echo query strings or fragments back to Telegram."""
    parts = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path or "/", "", ""))


def extract_numbered_link(command):
    if not LINKS_RE.search(command) or not OPEN_RE.search(command):
        return None
    found = NUMBER_RE.search(command)
    if found:
        return int(found.group(1))
    return None


def query_after_find(command):
    if not FIND_RE.search(command):
        return None
    parts = FIND_RE.split(command, maxsplit=1)
    tail = parts[-1].strip(" :—-.,!?«»\"' ")
    if tail:
        return tail[:160]
    # Also accept Uzbek word order: "браузердан Example қидир".
    front = re.sub(r"(?i)^(?:браузер(?:дан|да|ни)?|browser|хром(?:дан|да)?|chrome)(?:\s+)", "", parts[0]).strip()
    return front[:160]


class BrowserSession:
    """One short-lived ephemeral public browsing session for the bot owner."""

    def __init__(self):
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self.last_use = 0.0
        self.links = []

    async def start(self):
        if self.page is not None:
            self.last_use = time.monotonic()
            return
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise BrowserError("Playwright ўрнатилмаган. Railway'да Dockerfile.v7'ни ёқиш керак.") from None
        try:
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(
                headless=True,
                args=["--disable-dev-shm-usage", "--disable-background-networking", "--disable-extensions"],
            )
            self.context = await self.browser.new_context(
                accept_downloads=False,
                service_workers="block",
                java_script_enabled=True,
                ignore_https_errors=False,
                viewport={"width": 1100, "height": 750},
                permissions=[],
            )
            self.context.set_default_timeout(8000)
            self.context.set_default_navigation_timeout(18000)
            self.page = await self.context.new_page()
            await self.context.route("**/*", self._guard_request)  # Also cover popups
            self.page.on("dialog", lambda dialog: asyncio.create_task(dialog.dismiss()))
            self.page.on("popup", lambda popup: asyncio.create_task(popup.close()))
            self.last_use = time.monotonic()
        except Exception:
            await self.close()
            raise BrowserError("Chromium ишга тушмади. Dockerfile, хотира ва Railway Build Logs'ни текшир.") from None

    async def _guard_request(self, route):
        """Permit only public HTTPS GET. Block writes, local addresses and heavy media."""
        request = route.request
        try:
            if (request.method.upper() != "GET" or request.resource_type in
                    {"image", "font", "media", "websocket", "eventsource"}):
                await route.abort()
                return
            # Resolve every target before allowing it, including redirected and
            # subresource requests. This is best-effort filtering, not a firewall.
            await asyncio.wait_for(asyncio.to_thread(v6.validate_url, request.url), timeout=5)
            await route.continue_()
        except Exception:
            try:
                await route.abort()
            except Exception:
                pass

    async def open(self, url):
        # Validate before starting a possibly resource-heavy browser.
        await asyncio.wait_for(asyncio.to_thread(v6.validate_url, url), timeout=6)
        await self.start()
        try:
            response = await self.page.goto(url, wait_until="domcontentloaded", timeout=18000)
            if response is not None and response.status >= 400:
                raise BrowserError(f"Сайт HTTP {response.status} жавоб қайтарди.")
            await self.page.wait_for_timeout(700)  # Permit short JS rendering.
            await asyncio.wait_for(asyncio.to_thread(v6.validate_url, self.page.url), timeout=6)
            self.last_use = time.monotonic()
            self.links = []
            return await self.describe()
        except BrowserError:
            raise
        except Exception:
            raise BrowserError("Сайтни Chromium'да очиб бўлмади; вақт ёки тармоқ чеклови бўлиши мумкин.") from None

    async def describe(self):
        if not self.page or self.page.url == "about:blank":
            raise BrowserError("Ҳали саҳифа очилмаган. Аввал сайт URL'ини юбор.")
        self.last_use = time.monotonic()
        try:
            title = (await self.page.title())[:160] or "Саҳифа"
            body = (await self.page.locator("body").inner_text(timeout=5000))[:MAX_PAGE_TEXT]
        except Exception:
            raise BrowserError("Саҳифада ўқиладиган матн топилмади.") from None
        return f"🌐 {title}\n{plain_url(self.page.url)}\nРежим: Chromium (Playwright)\n\n{body or '(саҳифада матн йўқ)'}"

    async def show_links(self):
        if not self.page or self.page.url == "about:blank":
            raise BrowserError("Аввал сайтни оч.")
        try:
            results = await self.page.locator("a[href]").evaluate_all("""els =>
                els.filter(a => a.getClientRects().length > 0)
                   .slice(0, 60)
                   .map(a => ({title:(a.innerText || a.getAttribute('aria-label') || '').trim().slice(0,90), url:a.href}))
            """)
        except Exception:
            raise BrowserError("Ҳаволаларни ўқиб бўлмади.") from None
        valid = []
        current_host = urllib.parse.urlsplit(self.page.url).hostname
        for item in results:
            target = item.get("url", "")
            try:
                v6.validate_url(target, resolve=False)
                if urllib.parse.urlsplit(target).hostname != current_host:
                    continue  # No implicit navigation to another domain.
            except (v6.WebSafetyError, v6.WebFetchError, ValueError):
                continue
            valid.append({"url": target, "title": item.get("title") or "Ҳавола"})
            if len(valid) >= MAX_LINKS:
                break
        self.links = valid
        self.last_use = time.monotonic()
        if not valid:
            return "Бу саҳифада очиш мумкин бўлган ички HTTPS ҳаволалар топилмади."
        return "🔗 Шу сайтдаги ҳаволалар:\n" + "\n".join(
            f"{i}. {item['title'][:65]} — {plain_url(item['url'])}" for i, item in enumerate(valid, 1)
        ) + "\n\nМасалан: «Жарвис, браузер 1-ҳаволани оч»"

    async def follow_link(self, index):
        if not isinstance(index, int) or index < 1 or index > len(self.links):
            raise BrowserError("Ҳавола рақами топилмади. Аввал «Жарвис, браузер ҳаволаларини кўрсат» деб ёз.")
        target = self.links[index - 1]["url"]
        if urllib.parse.urlsplit(target).hostname != urllib.parse.urlsplit(self.page.url).hostname:
            raise BrowserError("Бошқа доменга ўтиш учун унинг HTTPS манзилини алоҳида юбор.")
        return await self.open(target)

    async def search_page(self, phrase):
        if not phrase or len(phrase) < 2:
            raise BrowserError("Қидирадиган сўзни ҳам ёз. Масалан: «Жарвис, браузердан Example қидир».")
        if not self.page or self.page.url == "about:blank":
            raise BrowserError("Аввал сайтни оч.")
        text = (await self.page.locator("body").inner_text(timeout=5000))[:20_000]
        at = text.casefold().find(phrase.casefold())
        self.last_use = time.monotonic()
        if at < 0:
            return "🔍 Саҳифа матнида бу ибора топилмади."
        excerpt = text[max(0, at - 180):at + len(phrase) + 340]
        return "🔍 Топилди:\n" + excerpt

    async def screenshot(self):
        if not self.page or self.page.url == "about:blank":
            raise BrowserError("Аввал сайтни оч.")
        try:
            img = await self.page.screenshot(type="png", full_page=False, timeout=12000, animations="disabled")
            self.last_use = time.monotonic()
            if len(img) > 7_000_000:
                raise BrowserError("Скриншот ҳажми жуда катта.")
            return img
        except BrowserError:
            raise
        except Exception:
            raise BrowserError("Скриншотни олиб бўлмади.") from None

    async def close(self):
        for obj in (self.context, self.browser, self.playwright):
            if obj is not None:
                try:
                    await asyncio.wait_for(obj.stop() if obj is self.playwright else obj.close(), timeout=6)
                except Exception:
                    pass
        self.context = None
        self.browser = None
        self.playwright = None
        self.page = None
        self.links = []
        self.last_use = 0.0


AGENT = BrowserSession()
LOCK = asyncio.Lock()


async def browser_message(legacy, update, context, command):
    msg = update.effective_message
    if update.effective_chat.type != "private" or not legacy._is_owner(update):
        await msg.reply_text("🔐 Браузер фақат бот эгасининг шахсий Telegram чатида ишлайди.")
        return
    if LOCK.locked():
        await msg.reply_text("⏳ Браузер банд. Бироздан кейин қайта юбор.")
        return
    async with LOCK:
        try:
            if AGENT.last_use and time.monotonic() - AGENT.last_use > IDLE_SECONDS:
                await AGENT.close()
            if CLOSE_RE.search(command):
                await AGENT.close()
                await msg.reply_text("✅ Браузер сеанси ёпилди; хотирадаги саҳифа сақланмади.")
                return
            url = v6.extract_url(command)
            link_index = extract_numbered_link(command)
            if url:
                await msg.reply_text("🌐 Chromium браузерида очяпман...")
                output = await asyncio.wait_for(AGENT.open(url), timeout=38)
                await msg.reply_text(output[:3800])
            elif link_index is not None:
                await msg.reply_text("🔗 Танланган ҳаволани очяпман...")
                output = await asyncio.wait_for(AGENT.follow_link(link_index), timeout=38)
                await msg.reply_text(output[:3800])
            elif SHOT_RE.search(command):
                img = await asyncio.wait_for(AGENT.screenshot(), timeout=18)
                f = io.BytesIO(img)
                f.name = "jarvis_v7_page.png"
                await msg.reply_photo(photo=f, caption="📸 Chromium саҳифасининг скриншоти")
            elif LINKS_RE.search(command):
                output = await asyncio.wait_for(AGENT.show_links(), timeout=15)
                await msg.reply_text(output[:3800])
            elif FIND_RE.search(command):
                output = await asyncio.wait_for(AGENT.search_page(query_after_find(command)), timeout=12)
                await msg.reply_text(output[:3800])
            elif AGENT.page is not None:
                await msg.reply_text((await AGENT.describe())[:3800])
            else:
                available = importlib.util.find_spec("playwright") is not None
                await msg.reply_text(
                    "🌐 JARVIS v7 — Chromium браузер\n"
                    + ("Python Playwright: топилди. Chromium ишлашини сайт очиб синаймиз.\n"
                       if available else "⚠️ Playwright ҳали ўрнатилмаган; Dockerfile.v7 керак.\n")
                    + "Жарвис, браузерда https://example.com оч\n"
                    + "Жарвис, браузер ҳаволаларини кўрсат\n"
                    + "Жарвис, браузер 1-ҳаволани оч\n"
                    + "Жарвис, браузер скриншот\n"
                    + "Жарвис, браузерни ёп\n\n"
                    + "Фақат очиқ HTTPS сайтлар; аккаунтга кириш, шакл юбориш ва файл юклаш ҳали йўқ."
                )
        except (v6.WebSafetyError, v6.WebFetchError, BrowserError) as exc:
            await msg.reply_text("⚠️ " + str(exc))
        except asyncio.TimeoutError:
            await AGENT.close()
            await msg.reply_text("⚠️ Браузер иши узоқ давом этди. Сеанс ёпилди; қайта синаб кўр.")
        except Exception as exc:
            LOG.warning("v7 request failed (%s)", type(exc).__name__)
            await AGENT.close()
            await msg.reply_text("⚠️ Браузерда хато. Railway Deploy Logs'ни текшир; токенларни юборманг.")


def install(legacy):
    v6.install(legacy)
    previous_dispatch = legacy.dispatch_user_text
    old_shutdown = legacy.post_shutdown

    async def v7_dispatch(update, context, text):
        command = user_command(text)
        if command is not None:
            await browser_message(legacy, update, context, command)
        else:
            await previous_dispatch(update, context, text)

    async def v7_shutdown(application):
        await AGENT.close()
        await old_shutdown(application)

    legacy.dispatch_user_text = v7_dispatch
    legacy.post_shutdown = v7_shutdown


def main():
    import bot as legacy
    logging.getLogger("httpx").setLevel(logging.WARNING)
    install(legacy)
    legacy.main()


if __name__ == "__main__":
    main()
