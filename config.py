import os

HOST_NAME = 'http://diglib.eg.org'
MAX_DOWNLOAD_TRIES = 10
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")
DOWNLOAD_POOL_SIZE = 10
PARSE_POOL_SIZE=10

LOGIN = ''
PWD = ''
