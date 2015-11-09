from gevent import monkey
monkey.patch_all()

import gevent
import gevent.pool
import requests
import colorama
import re
from colorama import Fore, Style
from bs4 import BeautifulSoup
import os
import config
import sys


class Prefices:
    INFO = '{start}[ INFO ]{end}'.format(
        start=Style.BRIGHT,
        end=Style.RESET_ALL
    )
    WARN = '{start}[ WARN ]{end}'.format(
        start=Fore.YELLOW,
        end=Style.RESET_ALL
    )
    FAIL = '{start}[ FAIL ]{end}'.format(
        start=Fore.RED,
        end=Style.RESET_ALL
    )
    OK = '{start}[  OK  ]{end}'.format(
        start=Fore.GREEN,
        end=Style.RESET_ALL
    )


if len(sys.argv) < 2:
    print "Use with 1st argument as search string"
    exit (-1)

search_str = sys.argv[1].encode('utf8')
print '{p} Searching for "{s}"'.format(s=search_str, p=Prefices.INFO)

pool = gevent.pool.Pool(config.SEARCH_POOL_SIZE)
parse_pool = gevent.pool.Pool(config.PARSE_POOL_SIZE)
download_pool = gevent.pool.Pool(config.DOWNLOAD_POOL_SIZE)
search_file_pool = gevent.pool.Pool(100)

pf_regex = re.compile(r'[\/\\\:\,\.\;\!\?\-\s]+', re.IGNORECASE)


''' Clean links for PDF page (they can start with hostname or just /) '''
def clean_link(link):
    if link.startswith('/'):
        return config.HOST_NAME + link
    else:
        return link


''' Updates searches.txt in every article directory '''
def update_searches(doc_path, new_search_str):
    new_search_str = new_search_str.lower()
    filename = os.path.join(doc_path, config.SEARCH_TAG_FILE)
    if not os.path.isfile(filename):
        with open(filename, 'a') as f:
            f.write(new_search_str + '\n')
            return
    with open(filename, 'r') as f:
        lines = (l.strip() for l in f.readlines())
        if new_search_str in lines:
            return
    with open(filename, 'a') as f:
        f.write(new_search_str + '\n')


''' Authenticates user. Returns auth cookie '''
def authenticate(url, login, pwd):
    cookie_name = 'JSESSIONID'
    auth_params = {
        "login_email": login,
        "login_password": pwd,
        "submit": "Sign in"
    }

    r = requests.post(url, data=auth_params, allow_redirects=False)
    if r.status_code == 302:
        for c in r.cookies:
            if c.name == cookie_name:
                result = {}
                result[cookie_name] = c.value
                return result
    return None


''' Returns list of search pages for given query '''
def search(query, rpp=10, cookies=None):
    cookies = cookies or {}
    url = "{host}/discover?&scope=%2F&query={query}&submit=Go&rpp={rpp}".format(query=query, rpp=rpp, host=config.HOST_NAME)
    r = requests.get(url, cookies=cookies)
    if r.status_code == 200:
        soup = BeautifulSoup(r.text, 'html.parser')
        pagelist = soup.find_all('ul', 'pagination-links')
        pages = None
        if len(pagelist) > 0:
            pagelist = pagelist[0]
            lpl = [l for l in pagelist.children if l != u'\n' and l.has_attr('class')]
            if len(lpl) > 0:
                # First try to find last-page-link
                ll = [l for l in lpl if l.attrs['class'][0] == u'last-page-link']
                if len(ll) > 0:
                    pages = int(ll[0].text.strip())
                else:
                    ll = [l for l in lpl if l.attrs['class'][0] == u'page-link']
                    if len(ll) > 0:
                        pages = int(ll[len(ll) - 1].text.strip())
        if pages is not None:
            print '{p} Found {pgs} search page(s)'.format(pgs=pages, p=Prefices.INFO)
            pages_to_crawl = ['{host}/discover?scope=%2F&rpp={rpp}&page={page}&query={query}&group_by=none'.format(
                query=query,
                rpp=rpp,
                page=l,
                host=config.HOST_NAME
            ) for l in range(1, pages + 1)]
            return pages_to_crawl
        else:
            print '{p} Can not find list of search pages'.format(Prefices.WARN)
            return []


''' Donwloads PDF file '''
def download_document(url, filename, cookies=None, tries=0):
    if tries > config.MAX_DOWNLOAD_TRIES:
        print '{p} Downloading "{url}" to "{fn}" failed: tries exceeded'.format(
            url=url,
            fn=filename,
            p=Prefices.FAIL
        )
        return

    print '{p} Downloading {url} -> {fn}'.format(url=url, fn=filename, p=Prefices.INFO)

    cookies = cookies or {}
    r = requests.get(url, cookies=cookies, stream=True)
    if r.status_code == 200:
        with open(filename, 'wb') as f:
            for chunk in r.iter_content(chunk_size=4096):
                if chunk:
                    f.write(chunk)
        print '{p} Downloading {url} -> {fn} done'.format(url=url, fn=filename, p=Prefices.OK)
    else:
        print '{p} Downloading {url} failed due to status {status}'.format(
            url=url,
            status=r.status_code,
            p=Prefices.WARN
        )
        download_pool.spawn(download_document, url=url, filename=filename, cookies=cookies, tries=tries+1)


''' Finds PDF links on page '''
def crawl_for_pdf(url, doc_path, cookies=None, tries=0):
    if tries > config.MAX_DOWNLOAD_TRIES:
        print '{p} Parsing PDF links page "{url}" for doc_path "{dp}"'.format(
            url=url,
            dp=doc_path,
            p=Prefices.FAIL
        )
        return

    cookies = cookies or {}
    r = requests.get(url, cookies=cookies)
    if r.status_code == 200:
        soup = BeautifulSoup(r.text, 'html.parser')
        links = list(set([l.attrs['href'] for l in soup.find_all('a') if config.DOWLOAD_EXTENSIONS_RE.search(l.attrs['href'])]))
        links = map(clean_link, links)
        for link in links:
            filename = None
            try:
                filename = os.path.join(doc_path, link.split('/')[-1].split('#')[0].split('?')[0].encode('utf8'))
                download_pool.spawn(download_document, url=link, filename=filename, cookies=cookies, tries=0)
            except UnicodeDecodeError as e:
                print '{p} Reparsing PDF page {url} -> {dp} due to "{e}"'.format(
                    url=url,
                    e=e,
                    dp=doc_path,
                    p=Prefices.WARN
                )
                parse_pool.spawn(crawl_for_pdf, url=url, doc_path=doc_path, cookies=cookies, tries=tries+1)
    else:
        print '{p} Reparsing PDF page {url} failed due to HTTP status {st}'.format(
            url=url,
            st=r.status_code,
            p=Prefices.WARN
        )
        parse_pool.spawn(crawl_for_pdf, url=url, doc_path=doc_path, cookies=cookies, tries=tries+1)


''' Finds links on given search page '''
def crawl_search(url, cookies=None):
    cookies = cookies or {}
    r = requests.get(url, cookies=cookies)
    if r.status_code == 200:
        soup = BeautifulSoup(r.text, 'html.parser')
        new_docs = [(c.text.strip(), config.HOST_NAME + c.attrs['href']) for divs in soup.find_all('div', 'artifact-title') for c in divs.children if c.name == 'a']
        print '{p} Parsing "{url}", found {num} document(s)'.format(
            url=url,
            num=len(new_docs),
            p=Prefices.OK
        )
        for (name, url) in new_docs:
            name = name.encode('utf8')
            name = pf_regex.sub(' ', name)
            doc_path = os.path.join(config.DOWNLOAD_DIR, name)

            already_downloaded = os.path.exists(doc_path)

            if not already_downloaded:
                os.mkdir(doc_path)
            search_file_pool.spawn(update_searches, doc_path=doc_path, new_search_str=search_str)
            if not already_downloaded:
                parse_pool.spawn(crawl_for_pdf, url=url, doc_path=doc_path, cookies=cookies, tries=0)
            else:
                print '{p} Folder for "{name}" already exists'.format(name=name, p=Prefices.WARN)
    else:
        print '{p} Parsing "{url}" failed'.format(url=url, p=Prefices.FAIL)


colorama.init(autoreset=True)

auth = gevent.spawn(
    authenticate,
    url='{host}/password-login'.format(host=config.HOST_NAME),
    login=config.LOGIN,
    pwd=config.PWD)
auth.join()
cookies = auth.value

if cookies is not None:
    srch = gevent.spawn(search, query=search_str, cookies=cookies)
    srch.join()
    pages = srch.value
    for url in pages:
        pool.spawn(crawl_search, url=url, cookies=cookies)
    pool.join()
    download_pool.join()
    search_file_pool.join()
else:
    print '{p} Can not authenticate.'.format(p=Prefices.FAIL)
    exit(-1)
