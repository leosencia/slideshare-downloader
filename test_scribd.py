import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bs4 import BeautifulSoup

import scribd
import slideshare2pdf as downloader
import test_slideshare2pdf as slideshare_tests


def reader_page(numbers=(1, 2), count=2, blur="false"):
    pages = "\n".join('''docManager.addPage({
        pageNum: %d, origWidth: 902, origHeight: 1167, fonts: [4,5],
        containerElem: document.getElementById("outer_page_%d"),
        blur: %s,
        contentUrl: "https://html.scribdassets.com/example/pages/%d-test.jsonp"
    });''' % (number, number, blur, number) for number in numbers)
    return BeautifulSoup(
        '<meta property="og:title" content="Example document | PDF">'
        '<script>docManager.setupPaidDocument([1,2], %d);%s</script>' % (count, pages),
        "html.parser",
    )


class ScribdExtractionTests(unittest.TestCase):
    def test_reader_pages_sort_numerically_and_preserve_dimensions(self):
        pages, _ = scribd.extract_pages(reader_page(numbers=(2, 1)))
        self.assertEqual([page.number for page in pages], [1, 2])
        self.assertEqual((pages[0].width, pages[0].height), (902, 1167))
        self.assertEqual(pages[0].fonts, [4, 5])

    def test_blurred_page_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "restricts some pages"):
            scribd.extract_pages(reader_page(blur="true"))

    def test_preview_and_duplicate_pages_are_rejected(self):
        for numbers in ((1,), (1, 1), (1, 3), ()):
            with self.subTest(numbers=numbers), self.assertRaises(ValueError):
                scribd.extract_pages(reader_page(numbers=numbers))

    def test_access_check_does_not_become_empty_pdf(self):
        with self.assertRaisesRegex(ValueError, "No Scribd reader pages"):
            scribd.extract_pages(BeautifulSoup("<title>Login</title>", "html.parser"))

    def test_malformed_page_metadata_has_clear_error(self):
        soup = BeautifulSoup(str(reader_page()).replace("origWidth: 902,", ""), "html.parser")
        with self.assertRaisesRegex(ValueError, "metadata has changed"):
            scribd.extract_pages(soup)

    def test_jsonp_is_parsed_as_data_and_active_content_removed(self):
        html = '<div class="newpage" id="page1"><script>bad()</script><img onerror="bad()" orig="example"></div>'
        page = scribd.page_html("window.page1_callback(" + json.dumps([html]) + ");", 1)
        self.assertIsNone(page.find("script"))
        self.assertNotIn("onerror", page.img.attrs)
        for payload in ("alert('bad')", "page2_callback([]);", 'page1_callback(["<p>Login</p>"]);'):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                scribd.page_html(payload, 1)

    def test_legacy_asset_host_and_unexpected_hosts(self):
        self.assertEqual(scribd.asset_url("http://html.scribd.com/example/image.jpg"),
                         "https://html.scribdassets.com/example/image.jpg")
        for url in ("https://scribdassets.com.evil.test/image", "file:///etc/passwd", "http://localhost/image"):
            with self.subTest(url=url), self.assertRaisesRegex(ValueError, "Unexpected Scribd asset"):
                scribd.asset_url(url)


class ScribdDownloadTests(unittest.TestCase):
    def test_scribd_dispatch_renders_and_converts_instead_of_extracting_slides(self):
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(downloader, "CURRENT", Path(folder)), \
                patch.object(downloader.requests, "Session") as session_class, \
                patch.object(scribd, "render_pages") as render, \
                patch.object(downloader, "convert_pdf", return_value=Path("Example_document.pdf")) as convert, \
                patch.object(downloader, "extract_slide_urls") as slides:
            session = session_class.return_value.__enter__.return_value
            session.get.return_value = slideshare_tests.DownloadTests.response(self, str(reader_page()).encode())
            result = downloader.download_images("https://www.scribd.com/document/123/example")
            self.assertEqual(result, Path("Example_document.pdf"))
            self.assertEqual(convert.call_args.args[1], "Example_document.pdf")
            self.assertEqual(render.call_args.args[1], session)
            self.assertEqual(render.call_args.args[2], convert.call_args.args[0])
            slides.assert_not_called()

    def test_restricted_document_stops_before_render_or_conversion(self):
        with patch.object(downloader.requests, "Session") as session_class, \
                patch.object(scribd, "render_pages") as render, \
                patch.object(downloader, "convert_pdf") as convert:
            session = session_class.return_value.__enter__.return_value
            session.get.return_value = slideshare_tests.DownloadTests.response(self, str(reader_page(blur="true")).encode())
            with self.assertRaisesRegex(ValueError, "restricts some pages"):
                downloader.download_images("https://www.scribd.com/document/123/example")
            render.assert_not_called()
            convert.assert_not_called()

    def test_studocu_error_is_specific_and_does_not_fetch_slides(self):
        with patch.object(downloader.requests, "Session") as session_class:
            with self.assertRaisesRegex(ValueError, "Studocu link"):
                downloader.download_images("https://www.studocu.com/ph/document/example/163609477")
            session_class.assert_not_called()

    def test_interactive_prompt_mentions_both_supported_services(self):
        with patch("builtins.input", return_value="scribd.com/document/123/example") as prompt, \
                patch.object(downloader, "download_images") as download, \
                patch.object(downloader.sys, "argv", ["slideshare2pdf.py"]), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(downloader.main(), 0)
            self.assertIn("Scribd", prompt.call_args.args[0])
            download.assert_called_once_with("https://scribd.com/document/123/example")


if __name__ == "__main__":
    unittest.main()
