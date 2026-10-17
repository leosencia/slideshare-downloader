import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests
from bs4 import BeautifulSoup
from PIL import Image

import slideshare2pdf as downloader


def metadata_page(count=3):
    data = {"props": {"pageProps": {"slideshow": {
        "totalSlides": count,
        "slides": {
            "host": "https://image.slidesharecdn.com",
            "imageLocation": "example-deck",
            "title": "A-Title-ending-in-g",
            "imageSizes": [
                {"width": 2048, "quality": 75},
                {"width": 320, "quality": 85},
            ],
        },
        "recommendationsByLocation": {"rightRail": [{"totalSlides": 99}]},
    }}}}
    return '<script id="__NEXT_DATA__" type="application/json">{}</script>'.format(
        json.dumps(data)
    )


class SlideExtractionTests(unittest.TestCase):
    def extract(self, html):
        return downloader.extract_slide_urls(BeautifulSoup(html, "html.parser"))

    def test_metadata_uses_largest_size_and_exact_slide_count(self):
        self.assertEqual(self.extract(metadata_page()), [
            "https://image.slidesharecdn.com/example-deck/75/"
            "A-Title-ending-in-g-{}-2048.jpg".format(index)
            for index in range(1, 4)
        ])

    def test_legacy_images_use_their_own_urls_and_largest_srcset(self):
        html = '''
            <script id="__NEXT_DATA__">invalid JSON</script>
            <img src="https://example.com/recommended.jpg">
            <img data-testid="vertical-slide-image"
                 srcset="https://example.com/first-large.jpg 2048w,
                         https://example.com/first-small.jpg 320w">
            <img data-testid="vertical-slide-image"
                 src="https://example.com/second.jpg">
            <img data-testid="vertical-slide-image"
                 src="https://example.com/second.jpg">
        '''
        self.assertEqual(self.extract(html), [
            "https://example.com/first-large.jpg",
            "https://example.com/second.jpg",
        ])

    def test_empty_page_has_actionable_error(self):
        with self.assertRaisesRegex(ValueError, "No slide images found"):
            self.extract("<html><title>Access check</title></html>")

    def test_empty_metadata_does_not_create_empty_pdf(self):
        with self.assertRaisesRegex(ValueError, "No slide images found"):
            self.extract(metadata_page(count=0))


class DownloadTests(unittest.TestCase):
    def response(self, content, content_type="text/html", status=200):
        response = requests.Response()
        response.status_code = status
        response._content = content
        response.headers["Content-Type"] = content_type
        response.url = "https://example.com/slide"
        return response

    def test_download_and_convert_produces_complete_pdf(self):
        image = io.BytesIO()
        Image.new("RGB", (32, 18), "white").save(image, format="JPEG")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pdf_path = root / "result.pdf"
            real_convert = downloader.convert_pdf
            with patch.object(downloader, "CURRENT", root), \
                    patch.object(downloader.requests, "Session") as session_class, \
                    patch.object(downloader, "convert_pdf", side_effect=lambda folder, name:
                                 real_convert(folder, pdf_path)) as convert, \
                    contextlib.redirect_stdout(io.StringIO()):
                session = session_class.return_value.__enter__.return_value
                session.get.side_effect = [
                    self.response(metadata_page().encode()),
                    *[self.response(image.getvalue(), "image/jpeg") for _ in range(3)],
                ]
                self.assertEqual(downloader.download_images("https://example.com/deck#2"), pdf_path)
                self.assertEqual(session.get.call_args_list[0].args[0], "https://example.com/deck")
                self.assertEqual(convert.call_args.args[1], "A_Title_ending_in_g.pdf")
                self.assertEqual(len(list((root / "pdf_images").glob("*/*.jpg"))), 3)
                self.assertTrue(pdf_path.read_bytes().startswith(b"%PDF-"))

    def test_http_error_stops_before_conversion(self):
        with patch.object(downloader.requests, "Session") as session_class, \
                patch.object(downloader, "convert_pdf") as convert:
            session = session_class.return_value.__enter__.return_value
            session.get.return_value = self.response(b"Forbidden", status=403)
            with self.assertRaises(requests.HTTPError):
                downloader.download_images("https://example.com/deck")
            convert.assert_not_called()

    def test_html_instead_of_slide_stops_before_conversion(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(downloader, "CURRENT", Path(directory)), \
                patch.object(downloader.requests, "Session") as session_class, \
                patch.object(downloader, "convert_pdf") as convert, \
                contextlib.redirect_stdout(io.StringIO()):
            session = session_class.return_value.__enter__.return_value
            session.get.side_effect = [
                self.response(metadata_page().encode()),
                self.response(b"<html>Access check</html>"),
            ]
            with self.assertRaisesRegex(ValueError, "Slide 1 did not return an image"):
                downloader.download_images("https://example.com/deck")
            convert.assert_not_called()


class ConversionTests(unittest.TestCase):
    def test_empty_directory_does_not_call_converter_or_write_pdf(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(downloader.img2pdf, "convert") as convert:
            output = Path(directory) / "output.pdf"
            with self.assertRaisesRegex(ValueError, "No downloaded slide images"):
                downloader.convert_pdf(directory, output)
            convert.assert_not_called()
            self.assertFalse(output.exists())

    def test_slide_numbers_sort_numerically_and_ignore_non_images(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(downloader.img2pdf, "convert", return_value=b"%PDF-") as convert, \
                contextlib.redirect_stdout(io.StringIO()):
            root = Path(directory)
            for name in ("10.jpg", "2.jpg", "1.jpg", "notes.txt"):
                (root / name).touch()
            downloader.convert_pdf(root, root / "output.pdf")
            self.assertEqual(
                [Path(path).name for path in convert.call_args.args[0]],
                ["1.jpg", "2.jpg", "10.jpg"],
            )


if __name__ == "__main__":
    unittest.main()
