import os
import re

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR = os.path.join(BASE_DIR, "new_downloads")
DOWLOAD_EXTENSIONS_RE = re.compile('|'.join(map(lambda s: '\\' + s, [
    '.pdf',
    '.jpg',
    '.jpeg',
    '.ps',
    '.eps',
    '.svg',
    '.tex',
    '.latex'
])), re.IGNORECASE)

LOGIN = ''
PWD = ''
HOST_NAME = 'http://diglib.eg.org'
MAX_DOWNLOAD_TRIES = 10

# Pools
DOWNLOAD_POOL_SIZE = 10
SEARCH_POOL_SIZE=10
PARSE_POOL_SIZE=10

SEARCH_TAG_FILE = 'searches.txt'
