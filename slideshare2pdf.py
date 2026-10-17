#!/usr/bin/env python
# -*- coding: utf-8 -*-
import json
import re
import sys
import tempfile
from pathlib import Path
from time import localtime, strftime
from urllib.parse import urldefrag, urlsplit

import img2pdf
import requests
from bs4 import BeautifulSoup


CURRENT = Path(__file__).resolve().parent
REQUEST_TIMEOUT = (10, 60)


def extract_slide_urls(soup):
    """Read this presentation's slide metadata, excluding recommendations."""
    script = soup.find("script", id="__NEXT_DATA__")
    if script:
        try:
            data = json.loads(script.string or script.get_text())
            slideshow = data["props"]["pageProps"]["slideshow"]
            slides = slideshow["slides"]
            size = max(slides["imageSizes"], key=lambda item: int(item["width"]))
            count = int(slideshow["totalSlides"])
            if count > 0:
                prefix = "{}/{}/{}/{}".format(
                    slides["host"].rstrip("/"),
                    slides["imageLocation"].strip("/"),
                    size["quality"],
                    slides["title"],
                )
                return [
                    "{}-{}-{}.jpg".format(prefix, index, size["width"])
                    for index in range(1, count + 1)
                ]
        except (KeyError, TypeError, ValueError):
            # Older pages may only expose slide URLs in the HTML.
            pass

    urls = []
    for image in soup.select('img[data-testid="vertical-slide-image"]'):
        candidates = []
        for candidate in image.get("srcset", "").split(","):
            parts = candidate.split()
            if not parts:
                continue
            width = 0
            if len(parts) > 1 and re.fullmatch(r"\d+w", parts[1]):
                width = int(parts[1][:-1])
            candidates.append((width, parts[0]))
        image_url = (
            max(candidates, key=lambda item: item[0])[1]
            if candidates else image.get("src")
        )
        if image_url and image_url not in urls:
            urls.append(image_url)

    if not urls:
        raise ValueError(
            "No slide images found. SlideShare may have changed its page format, "
            "or returned a login/access-check page. Open the URL in your browser "
            "to confirm the presentation is available."
        )
    return urls


def download_images(url):
    url = urldefrag(url)[0]
    with requests.Session() as session:
        response = session.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "html.parser")
        image_urls = extract_slide_urls(soup)

        # Remove the slide number and image width without stripping title letters.
        image_name = Path(urlsplit(image_urls[0]).path).name
        name = re.sub(r"-\d+-\d+\.[^.]+$", "", image_name)
        pdf_f = (re.sub(r"[^0-9a-zA-Z]+", "_", name).strip("_") or "result") + ".pdf"
        image_root = CURRENT / "pdf_images"
        image_root.mkdir(exist_ok=True)
        image_dir = Path(tempfile.mkdtemp(
            prefix=strftime("%Y%m%d_%H%M%S_", localtime()), dir=image_root
        ))

        print("1. Download Images ({} slides):".format(len(image_urls)))
        for index, image_url in enumerate(image_urls, 1):
            print("Downloading {}/{}: {}".format(index, len(image_urls), image_url))
            image_response = session.get(image_url, timeout=REQUEST_TIMEOUT)
            image_response.raise_for_status()
            content_type = image_response.headers.get("Content-Type", "")
            if not image_response.content or (
                content_type and not content_type.lower().startswith("image/")
            ):
                raise ValueError(
                    "Slide {} did not return an image: {}".format(index, image_url)
                )
            (image_dir / "{}.jpg".format(index)).write_bytes(image_response.content)

    return convert_pdf(image_dir, pdf_f)


def convert_pdf(img_dir_name, pdf_f):
    image_dir = Path(img_dir_name)
    if not image_dir.is_absolute():
        image_dir = CURRENT / image_dir
    images = [
        path for path in image_dir.iterdir()
        if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg", ".png"}
    ] if image_dir.is_dir() else []
    images.sort(key=lambda path: [
        int(part) if part.isdigit() else part.lower()
        for part in re.split(r"(\d+)", path.name)
    ])
    if not images:
        raise ValueError("No downloaded slide images to convert in {}".format(image_dir))

    print("\n2. Convert Images to PDF")
    pdf_bytes = img2pdf.convert([str(path) for path in images])
    Path(pdf_f).write_bytes(pdf_bytes)
    print("\n3. Done: {}".format(pdf_f))
    return Path(pdf_f)


def main():
    url = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else input("Slideshare URL: ")
    url = url.strip().strip("\"'")
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        download_images(url)
    except (requests.RequestException, ValueError, OSError, img2pdf.ImageOpenError) as error:
        print("Error: {}".format(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
