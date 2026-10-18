import asyncio
import importlib.util
import os
import random
import re
import subprocess
import sys
import time
from html import unescape
from math import gcd
from types import SimpleNamespace
from urllib.parse import quote, unquote, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
AVAILABLE = os.path.join(ROOT, "available.txt")

BASE_URL = "https://soundcloud.com"
CONCURRENCY = 3
REQUEST_INTERVAL = 0.75
TIMEOUT = 12.0
RETRIES = 2
RATE_LIMIT_BACKOFF = 2.0

LETTERS = "abcdefghijklmnopqrstuvwxyz"
ALNUM = LETTERS + "0123456789"
PERMALINK_CHARS = ALNUM + "-_"

DEFAULT_LENGTHS = (4,)
DEFAULT_ALPHABET = PERMALINK_CHARS
EXAMPLES = "3L   4L   5L     3C   4C   5C     3P   4P   5P   3-5P"
PROMPT = "(!) type of username (default 4P): "

LOGO = r"""   ________  __  ___  _____  _______   ____  __  _____
  / __/ __ \/ / / / |/ / _ \/ ___/ /  / __ \/ / / / _ \
 _\ \/ /_/ / /_/ /    / // / /__/ /__/ /_/ / /_/ / // /
/___/\____/\____/_/|_/____/\___/____/\____/\____/____/"""

HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "accept-language": "en-US,en;q=0.8",
    "user-agent": "Mozilla/5.0 (compatible; SoundCloudUsernameChecker/1.0; public-profile-check)",
}

REQUIRED = ("aiohttp", "colorama")


def _fallback_colors():
    global Fore, Style, colorama_init
    Fore = SimpleNamespace(
        LIGHTBLUE_EX="",
        LIGHTGREEN_EX="",
        LIGHTRED_EX="",
        LIGHTYELLOW_EX="",
        LIGHTBLACK_EX="",
    )
    Style = SimpleNamespace(RESET_ALL="")
    colorama_init = lambda **_kwargs: None


def _load_libraries():
    global aiohttp, Fore, Style, colorama_init
    import aiohttp as aiohttp_module
    from colorama import Fore as color_fore
    from colorama import Style as color_style
    from colorama import init as init_colorama

    aiohttp = aiohttp_module
    Fore = color_fore
    Style = color_style
    colorama_init = init_colorama

    try:
        from colorama import just_fix_windows_console
        just_fix_windows_console()
    except (ImportError, AttributeError, OSError):
        colorama_init(autoreset=False)


try:
    _load_libraries()
except ImportError:
    aiohttp = None
    _fallback_colors()

def _set_colors():
    global BLUE, GREEN, RED, YEL, DIM, RST
    BLUE = Fore.LIGHTBLUE_EX
    GREEN = Fore.LIGHTGREEN_EX
    RED = Fore.LIGHTRED_EX
    YEL = Fore.LIGHTYELLOW_EX
    DIM = Fore.LIGHTBLACK_EX
    RST = Style.RESET_ALL


_set_colors()


def missing():
    return [name for name in REQUIRED if importlib.util.find_spec(name) is None]


def setup():
    packages = missing()
    if not packages:
        if aiohttp is None:
            _load_libraries()
            _set_colors()
        return True

    if os.environ.get("_SOUNDCLOUD_CHECKER_SETUP") == "1":
        print("  libraries could not be installed: " + ", ".join(packages))
        print("  install them manually:  py -m pip install " + " ".join(packages))
        return False

    os.environ["_SOUNDCLOUD_CHECKER_SETUP"] = "1"
    print("  installing libraries: " + ", ".join(packages) + " ...")
    for extra in ([], ["--user"]):
        try:
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "--disable-pip-version-check",
                 "-q", *extra, *packages],
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            pass
        if not missing():
            break

    packages = missing()
    if packages:
        print("  libraries could not be installed: " + ", ".join(packages))
        print("  install them manually:  py -m pip install aiohttp colorama")
        return False

    _load_libraries()
    _set_colors()
    return True


def clear():
    if os.name == "nt":
        os.system("cls")
    else:
        sys.stdout.write("\033[2J\033[H")
        sys.stdout.flush()


def banner():
    clear()
    print(BLUE + LOGO + RST)
    print()


def alphabet_name(alphabet):
    if alphabet == LETTERS:
        return "letters (a-z)"
    if alphabet == ALNUM:
        return "letters + digits (a-z 0-9)"
    return "permalink characters (a-z 0-9 _ -)"


def parse_type(text):
    text = text.strip().upper().replace(" ", "")
    lengths, alphabet = list(DEFAULT_LENGTHS), DEFAULT_ALPHABET

    if text:
        if text in ("L", "C", "P"):
            text = "4" + text
        match = re.fullmatch(r"(\d+(?:[-,]\d+)*)([LCP]?)", text)
        if not match:
            return None

        body, suffix = match.group(1), match.group(2)
        if "-" in body:
            if not re.fullmatch(r"\d+-\d+", body):
                return None
            start, end = (int(value) for value in body.split("-"))
            lengths = list(range(min(start, end), max(start, end) + 1))
        else:
            lengths = [int(value) for value in body.split(",")]

        lengths = sorted(set(lengths))
        if not lengths or lengths[0] < 3 or lengths[-1] > 25:
            return None
        alphabet = {"L": LETTERS, "C": ALNUM, "P": PERMALINK_CHARS, "": DEFAULT_ALPHABET}[suffix]

    if len(lengths) > 1 and lengths == list(range(lengths[0], lengths[-1] + 1)):
        number = f"{lengths[0]}-{lengths[-1]}"
    else:
        number = ", ".join(str(length) for length in lengths)
    return lengths, alphabet, f"{number} {alphabet_name(alphabet)}"


def ask_type():
    banner()
    print(f"   {DIM}{EXAMPLES}{RST}")
    print()
    print(f"   {YEL}{PROMPT}{RST}", end="")

    while True:
        try:
            text = input()
        except (EOFError, KeyboardInterrupt):
            print()
            return None

        chosen = parse_type(text)
        if chosen:
            return chosen
        print(f"   {DIM}not a type i know - try 3L, 5C or 3-5P{RST}")
        print(f"   {YEL}{PROMPT}{RST}", end="")


def validate_username(username):
    if not isinstance(username, str) or not 3 <= len(username) <= 25:
        return False
    if username != username.lower() or any(char not in PERMALINK_CHARS for char in username):
        return False
    if "soundcloud" in username:
        return False
    return True


def stream(lengths, alphabet):
    base = len(alphabet)
    blocks = [(length, base ** length) for length in sorted(lengths)]
    total = sum(size for _length, size in blocks)

    def name_of(index):
        for length, size in blocks:
            if index < size:
                chars = []
                for _ in range(length):
                    index, rest = divmod(index, base)
                    chars.append(alphabet[rest])
                return "".join(reversed(chars))
            index -= size
        return None

    if total <= 1:
        step = 1
        index = 0
    else:
        step = random.randrange(1, total)
        while gcd(step, total) != 1:
            step = random.randrange(1, total)
        index = random.randrange(total)

    for _ in range(total):
        name = name_of(index)
        if name is not None:
            yield name
        index = (index + step) % total


def _attributes(tag):
    attributes = {}
    pattern = re.compile(
        r"([a-zA-Z_:][a-zA-Z0-9_.:-]*)\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s>]+))"
    )
    for match in pattern.finditer(tag):
        value = next((part for part in match.groups()[1:] if part is not None), "")
        attributes[match.group(1).lower()] = unescape(value)
    return attributes


def _meta_values(html):
    values = {}
    for tag in re.findall(r"<meta\b[^>]*>", html, flags=re.IGNORECASE | re.DOTALL):
        attributes = _attributes(tag)
        key = (attributes.get("property") or attributes.get("name") or "").lower()
        if key and "content" in attributes:
            values[key] = attributes["content"]
    return values


def _canonical_url(html):
    for tag in re.findall(r"<link\b[^>]*>", html, flags=re.IGNORECASE | re.DOTALL):
        attributes = _attributes(tag)
        rel = attributes.get("rel", "").lower().split()
        if "canonical" in rel:
            return attributes.get("href", "")
    return ""


def _title(html):
    match = re.search(r"<title\b[^>]*>(.*?)</title\s*>", html, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    return unescape(re.sub(r"<[^>]+>", "", match.group(1))).strip()


def _is_candidate_profile_url(url, username):
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    if host not in ("soundcloud.com", "www.soundcloud.com"):
        return False
    parts = [unquote(part).lower() for part in parsed.path.split("/") if part]
    return len(parts) == 1 and parts[0] == username.lower()


def looks_like_profile_page(html, username, final_url):
    """Return True only when the page gives a positive signal for a profile."""
    normalized = html.lower().replace("\\/", "/").replace("&quot;", '"')
    metas = _meta_values(html)
    og_type = metas.get("og:type", "").lower()
    profile_types = {"profile", "music.musician", "music.artist"}
    identity_url = metas.get("og:url") or _canonical_url(html) or final_url

    if og_type in profile_types and _is_candidate_profile_url(identity_url, username):
        return True

    permalink = re.escape(username.lower())
    permalink_pattern = re.compile(
        rf"[\"']permalink(?:_url)?[\"']\s*:\s*[\"']"
        rf"(?:https?://(?:www\.)?soundcloud\.com/)?{permalink}(?:[/\"'?]|$)",
        flags=re.IGNORECASE,
    )
    user_kind = re.search(r"[\"']kind[\"']\s*:\s*[\"']user[\"']", normalized)
    if user_kind and permalink_pattern.search(normalized):
        return True

    title = _title(html).lower()
    if (_is_candidate_profile_url(final_url, username)
            and "soundcloud" in title
            and (" on soundcloud" in title or "| soundcloud" in title)):
        return True

    return False


def looks_like_not_found_page(html):
    lowered = html.lower()
    markers = (
        "we couldn't find that page",
        "we could not find that page",
        "we couldn't find the page",
        "this page doesn't exist",
        "this page does not exist",
        "the page you are looking for doesn't exist",
        "the page you are looking for does not exist",
        "page not found",
    )
    return any(marker in lowered for marker in markers)


def classify_profile_response(status, html, username, final_url):
    """Map a public profile response to taken/available/error conservatively."""
    if status in (404, 410):
        return "available"
    if 200 <= status < 300:
        if looks_like_profile_page(html, username, final_url):
            return "taken"
        if (_is_candidate_profile_url(final_url, username)
                and looks_like_not_found_page(html)):
            return "available"
    return "error"


class RequestPacer:
    """Space request starts apart to reduce load and avoid hammering the site."""
    def __init__(self, interval=REQUEST_INTERVAL):
        self.interval = interval
        self._lock = asyncio.Lock()
        self._next_at = 0.0

    async def wait(self):
        loop = asyncio.get_running_loop()
        async with self._lock:
            now = loop.time()
            delay = max(0.0, self._next_at - now)
            self._next_at = max(now, self._next_at) + self.interval
        if delay:
            await asyncio.sleep(delay)

    async def pause(self, seconds):
        loop = asyncio.get_running_loop()
        async with self._lock:
            self._next_at = max(self._next_at, loop.time() + seconds)


def _backoff(response, attempt):
    value = response.headers.get("Retry-After", "")
    try:
        return min(max(float(value), 1.0), 60.0)
    except (TypeError, ValueError):
        return min(RATE_LIMIT_BACKOFF * (2 ** attempt), 30.0)


def note_ratelimit(state, delay):
    state["ratelimit"] += 1
    now = time.time()
    if now - state["ratelimit_at"] < 2.0:
        return
    state["ratelimit_at"] = now
    print(f"{YEL}[ratelimit]{RST} {DIM}too many requests - waiting {round(delay, 1)}s{RST}",
          flush=True)


async def check(session, username, state, pacer=None):
    if not validate_username(username):
        return "invalid"

    pacer = pacer or RequestPacer(interval=0.0)
    url = f"{BASE_URL}/{quote(username, safe='-_')}"
    timeout = aiohttp.ClientTimeout(total=TIMEOUT) if aiohttp is not None else TIMEOUT

    for attempt in range(RETRIES + 1):
        try:
            await pacer.wait()
            async with session.get(url, allow_redirects=True, timeout=timeout) as response:
                if response.status in (404, 410):
                    return ("available" if _is_candidate_profile_url(str(response.url), username)
                            else "error")
                if response.status == 429:
                    delay = _backoff(response, attempt)
                    note_ratelimit(state, delay)
                    if attempt < RETRIES:
                        await pacer.pause(delay)
                        await asyncio.sleep(delay)
                        continue
                    return "error"
                if not 200 <= response.status < 300:
                    return "error"

                try:
                    html = await response.text(errors="replace")
                except TypeError:
                    html = await response.text()
                return classify_profile_response(
                    response.status, html, username, str(response.url)
                )
        except asyncio.CancelledError:
            raise
        except (asyncio.TimeoutError, OSError, ValueError):
            if attempt < RETRIES:
                await asyncio.sleep(0.25 * (attempt + 1))
        except Exception as exc:
            if aiohttp is not None and isinstance(exc, aiohttp.ClientError):
                if attempt < RETRIES:
                    await asyncio.sleep(0.25 * (attempt + 1))
                continue
            return "error"

    return "error"


async def worker(session, queue, state, out_file, pacer):
    while True:
        username = await queue.get()
        try:
            if username is None:
                return
            status = await check(session, username, state, pacer)
        finally:
            queue.task_done()

        state["checked"] += 1
        if status == "taken":
            state["taken"] += 1
            print(f"{RED}[taken]{RST} {username}", flush=True)
        elif status == "available":
            state["available"] += 1
            print(f"{GREEN}[available]{RST} {username}", flush=True)
            out_file.write(username + "\n")
            out_file.flush()
        elif status == "invalid":
            state["invalid"] += 1
        else:
            state["error"] += 1
            print(f"{DIM}[error] {username}{RST}", flush=True)


async def feeder(queue, names):
    for username in names:
        await queue.put(username)
    for _ in range(CONCURRENCY):
        await queue.put(None)


async def run(chosen, state):
    if aiohttp is None:
        raise RuntimeError("aiohttp is required; run setup() before starting the checker")

    lengths, alphabet, label = chosen
    queue = asyncio.Queue(maxsize=CONCURRENCY * 4)
    connector = aiohttp.TCPConnector(limit=CONCURRENCY, ttl_dns_cache=300)
    pacer = RequestPacer()
    os.makedirs(os.path.dirname(AVAILABLE), exist_ok=True)
    out_file = open(AVAILABLE, "a", encoding="utf-8")

    try:
        async with aiohttp.ClientSession(headers=HEADERS, connector=connector) as session:
            print(f"   {DIM}checking public SoundCloud profile URLs ...{RST}", flush=True)
            banner()
            print(f"   {DIM}{label}  |  workers {CONCURRENCY}  |  {REQUEST_INTERVAL:.2f}s between requests{RST}")
            print(f"   {DIM}unverified responses are reported as errors, not available{RST}")
            print()

            workers = [asyncio.create_task(worker(session, queue, state, out_file, pacer))
                       for _ in range(CONCURRENCY)]
            feed = asyncio.create_task(feeder(queue, stream(lengths, alphabet)))
            await asyncio.gather(feed, *workers)
    finally:
        out_file.close()


def summary(state, started):
    elapsed = max(time.time() - started, 0.001)
    print()
    print(f"   {BLUE}done{RST}  -  checked {state['checked']}  |  "
          f"{RED}taken {state['taken']}{RST}  |  {GREEN}available {state['available']}{RST}")
    if state["invalid"] or state["error"]:
        print(f"   {DIM}skipped {state['invalid'] + state['error']} "
              f"(invalid or unreachable){RST}")
    if state["ratelimit"]:
        print(f"   {YEL}rate limited {state['ratelimit']} times{RST}")
    print(f"   {DIM}{round(elapsed, 1)}s  |  {round(state['checked'] / elapsed, 2)}/s  "
          f"|  saved to available.txt{RST}")
    print(f"   {DIM}availability is advisory; confirm the URL during SoundCloud signup{RST}")


def main():
    if not setup():
        return 1

    chosen = ask_type()
    if chosen is None:
        banner()
        return 0

    state = {"checked": 0, "taken": 0, "available": 0, "invalid": 0,
             "error": 0, "ratelimit": 0, "ratelimit_at": 0.0}
    started = time.time()

    try:
        asyncio.run(run(chosen, state))
    except KeyboardInterrupt:
        pass
    except (OSError, RuntimeError) as exc:
        print(f"\n   {RED}could not reach SoundCloud: {exc}{RST}")
        return 1

    summary(state, started)
    return 0


if __name__ == "__main__":
    sys.exit(main())
