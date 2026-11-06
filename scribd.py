"""Render the public, unblurred pages exposed by Scribd's document reader."""

import base64
import json
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from bs4 import BeautifulSoup


@dataclass
class Page:
    number: int
    width: int
    height: int
    url: str
    fonts: list


def extract_pages(soup):
    scripts = "\n".join(script.get_text() for script in soup.find_all("script"))
    pages = []
    for block in re.findall(r"docManager\.addPage\(\s*\{(.*?)\}\s*\)", scripts, re.S):
        if not re.search(r"\bblur\s*:\s*false\b", block):
            raise ValueError("Scribd restricts some pages. Open the document on Scribd to download it with your account.")
        try:
            number, width, height = [int(re.search(r"\b" + key + r"\s*:\s*(\d+)", block)[1])
                                     for key in ("pageNum", "origWidth", "origHeight")]
            url = json.loads(re.search(r'\bcontentUrl\s*:\s*("[^"\n]+")', block)[1])
            fonts = json.loads(re.search(r"\bfonts\s*:\s*(\[[\d,\s]*\])", block)[1])
        except (TypeError, ValueError) as error:
            raise ValueError("Scribd's page metadata has changed; no PDF was created.") from error
        if min(number, width, height) <= 0:
            raise ValueError("Scribd returned invalid page dimensions or numbering.")
        pages.append(Page(number, width, height, url, fonts))
    count = re.search(r"docManager\.setupPaidDocument\([^;]*?,\s*(\d+)\s*\)", scripts)
    if not count:
        count = re.search(r'"page_count"\s*:\s*(\d+)', scripts)
    if not pages or not count:
        raise ValueError("No Scribd reader pages found. Open the URL in your browser to check for login or access verification.")
    pages.sort(key=lambda page: page.number)
    if [page.number for page in pages] != list(range(1, int(count[1]) + 1)):
        raise ValueError("Scribd exposed only a partial preview. Open the document on Scribd to download the complete file.")
    return pages, scripts


def asset_url(url):
    # This is the same legacy image-host substitution used by Scribd's reader.
    if url.startswith("http://html.scribd.com/"):
        url = url.replace("http://html.scribd.com/", "https://html.scribdassets.com/", 1)
    parts = urlsplit(url)
    if parts.scheme != "https" or not (parts.hostname or "").endswith(".scribdassets.com"):
        raise ValueError("Unexpected Scribd asset URL: {}".format(url))
    return url


def fetch(session, url, timeout):
    response = session.get(asset_url(url), timeout=timeout)
    response.raise_for_status()
    if not response.content:
        raise ValueError("Scribd returned an empty asset: {}".format(url))
    return response


def data_uri(content, mime):
    return "data:{};base64,{}".format(mime, base64.b64encode(content).decode("ascii"))


def page_html(payload, number):
    match = re.fullmatch(r"\s*(?:window\.)?page" + str(number) + r"_callback\s*\((.*)\);?\s*", payload, re.S)
    try:
        data = json.loads(match[1]) if match else None
    except ValueError as error:
        raise ValueError("Scribd returned invalid page data for page {}.".format(number)) from error
    if not isinstance(data, list) or not data or not isinstance(data[0], str):
        raise ValueError("Scribd returned no page content for page {}.".format(number))
    soup = BeautifulSoup(data[0], "html.parser")
    page = soup.select_one(".newpage")
    if page is None or page.get("id") != "page{}".format(number):
        raise ValueError("Scribd returned unexpected content for page {}.".format(number))
    for node in page.select("script, iframe, object, embed, link, style, noscript"):
        node.decompose()
    for node in [page, *page.find_all(True)]:
        for key in list(node.attrs):
            if key.lower().startswith("on"):
                del node[key]
    return page


def render_pages(soup, session, image_dir, timeout):
    pages, scripts = extract_pages(soup)
    try:
        from playwright.sync_api import Error, sync_playwright
    except ImportError as error:
        raise ValueError("Scribd needs Playwright. Run: python -m pip install -r requirements.txt") from error

    styles = [s.get_text() for s in soup.find_all("style") if ".text_layer" in s.get_text() and ".newpage" in s.get_text()]
    if not styles:
        raise ValueError("Scribd's reader styles are missing; no PDF was created.")
    css = "\n".join(styles) + "\nhtml,body{margin:0;padding:0;background:white;}"
    prefix = re.search(r'docManager\.assetPrefix\s*=\s*"([\w-]+)"', scripts)
    hosts = re.search(r"docManager\.fontAggregatorHosts\s*=\s*(\[[^\]]+\])", scripts)
    needed = {font for page in pages for font in page.fonts}
    loaded = set()
    for args in re.findall(r"docManager\.addFont\((.*?)\)\s*;", scripts):
        try:
            font_id, _, family, fallback, weight, style = json.loads("[" + args + "]")
        except (ValueError, TypeError) as error:
            raise ValueError("Scribd's font metadata has changed.") from error
        if font_id not in needed:
            continue
        if not prefix or not hosts or not re.fullmatch(r"ff\d+", family):
            raise ValueError("Scribd's font locations are missing or invalid.")
        url = "{}/{}/fonts/{:04d}.woff2".format(json.loads(hosts[1])[0].rstrip("/"), prefix[1], font_id)
        font = fetch(session, url, timeout)
        css += '\n@font-face{font-family:%s;src:url("%s");font-weight:%s;font-style:%s;}' % (
            family, data_uri(font.content, "font/woff2"), weight, style)
        css += '\ndiv.%s span{font-family:%s,%s;font-weight:%s;font-style:%s;}' % (
            family, family, fallback, weight, style)
        loaded.add(font_id)
    if needed != loaded:
        raise ValueError("Some Scribd fonts are missing; no PDF was created.")

    assets = {}
    with sync_playwright() as playwright:
        browser = None
        for options in ({"channel": "msedge"}, {"channel": "chrome"}, {}):
            try:
                browser = playwright.chromium.launch(headless=True, **options)
                break
            except Error:
                continue
        if browser is None:
            raise ValueError("No supported browser found. Run: python -m playwright install chromium")
        try:
            context = browser.new_context(java_script_enabled=False, device_scale_factor=2)
            context.route("**/*", lambda route: route.abort())
            view = context.new_page()
            view.set_default_timeout(timeout[1] * 1000)
            print("1. Render Scribd document ({} pages):".format(len(pages)))
            for page in pages:
                print("Rendering {}/{}".format(page.number, len(pages)))
                response = fetch(session, page.url, timeout)
                content = page_html(response.text, page.number)
                for image in content.find_all("img"):
                    source = image.get("orig") or image.get("src")
                    if not source:
                        raise ValueError("Scribd page {} has an image without a source.".format(page.number))
                    if source not in assets:
                        image_response = fetch(session, source, timeout)
                        mime = image_response.headers.get("Content-Type", "").split(";")[0].lower()
                        if mime not in {"image/jpeg", "image/png", "image/webp", "image/gif"}:
                            raise ValueError("Scribd returned a non-image asset for page {}.".format(page.number))
                        assets[source] = data_uri(image_response.content, mime)
                    image["src"] = assets[source]
                    image.attrs.pop("srcset", None)
                view.set_viewport_size({"width": page.width, "height": page.height})
                view.set_content("<!doctype html><meta charset=utf-8><style>" + css + "</style>" + str(content))
                view.evaluate("async () => { await document.fonts.ready; if ([...document.fonts].some(f => f.status === 'error')) throw Error('A document font failed to load'); await Promise.all([...document.images].map(i => i.decode())); }")
                view.locator(".newpage").screenshot(path=str(image_dir / "{}.png".format(page.number)), animations="disabled")
        except Error as error:
            raise ValueError("Scribd rendering failed; no PDF was created: {}".format(error)) from error
        finally:
            browser.close()
