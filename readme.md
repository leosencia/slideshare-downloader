# Slideshare Downloader

Download Slideshare without login and converted into pdf with high-resolution automatically.

## Environment

This code tested on Linux/Unix env and Python 3.


## Installation

```
git clone https://github.com/yodiaditya/slideshare-downloader.git
cd slideshare-downloader
python -m venv venv
source venv/bin/activate
pip3 install -r requirements.txt
```

## How to use

```
python slideshare2pdf.py [url]
```

The downloader reads the presentation metadata to download every slide at the
largest available image size, then saves the PDF in the current directory.
Downloaded images are kept in a separate folder under `pdf_images/` for each run.
URLs with slide fragments such as `#2` still download the full presentation.

If no slides are found or a request fails, the command exits with an error
instead of attempting to create an empty PDF.

Run the regression tests with `python -m unittest -v`.

Example:
```
python slideshare2pdf.py https://www.slideshare.net/JiangweiPan/reward-innovation-for-longterm-member-satisfaction
```

See the result: [reward_innovation_for_longterm_member_satisfaction.pdf](reward_innovation_for_longterm_member_satisfaction.pdf)
