# SlideShare and Scribd Downloader

Save SlideShare presentations and publicly accessible Scribd documents as PDFs.

## Environment

This code is tested on Linux/Unix and Python 3.


## Installation

```
git clone https://github.com/yodiaditya/slideshare-downloader.git
cd slideshare-downloader
python -m venv venv
```

Activate the virtual environment using the command for your shell:

**Linux/macOS (Bash or similar):**
```
source venv/bin/activate
```

**Windows PowerShell:**
```
.\venv\Scripts\Activate.ps1
```

**Windows Command Prompt:**
```
venv\Scripts\activate.bat
```

Then install the dependencies:
```
python -m pip install -r requirements.txt
```

Scribd rendering uses Microsoft Edge or Google Chrome if installed. Otherwise,
install Playwright's Chromium browser:

```
python -m playwright install chromium
```

## How to use

```
python slideshare2pdf.py [url]
python slideshare2pdf.py "https://www.scribd.com/document/607171419/Dlp-Format-Deped-docx"
```

The downloader reads the presentation metadata to download every slide at the
largest available image size, then saves the PDF in the current directory.
Downloaded images are kept in a separate folder under `pdf_images/` for each run.
URLs with slide fragments such as `#2` still download the full presentation.

For Scribd, the downloader renders the reader's public pages at double resolution,
including positioned text, embedded fonts, and images, then combines them into an
image-based PDF. This saves the visible document layout, not the original DOCX or
selectable text. Edge/Chrome/Chromium runs locally in headless mode.

Scribd documents with blurred pages or incomplete previews stop with an error.
The downloader does not log in or unlock restricted pages. Site format changes
or access checks can also prevent a download.

Studocu is a separate service and is not supported. Studocu links receive a
specific error directing you to the site's own Download option.

If no slides are found or a request fails, the command exits with an error
instead of attempting to create an empty PDF.

Run the regression tests with `python -m unittest -v`.

Example:
```
python slideshare2pdf.py https://www.slideshare.net/JiangweiPan/reward-innovation-for-longterm-member-satisfaction
```

See the result: [reward_innovation_for_longterm_member_satisfaction.pdf](reward_innovation_for_longterm_member_satisfaction.pdf)
