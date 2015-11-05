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


if len(sys.argv) < 2:
    print "Use with 1st argument as search string"
    exit (-1)

search_str = sys.argv[1].encode('utf8')
print 'Searching for "{s}"'.format(s=search_str)

pool = gevent.pool.Pool(config.PARSE_POOL_SIZE)
download_pool = gevent.pool.Pool(config.DOWNLOAD_POOL_SIZE)

pf_regex = re.compile(r'[\/\\\:\,\.\;\!\?\-\s]+', re.IGNORECASE)
ext_regex = re.compile(r'\.pdf|\.jpg|\.jpeg|\.ps|\.eps|\.tex|\.latex', re.IGNORECASE)

def clean_link(link):
    if link.startswith('/'):
        return config.HOST_NAME + link
    else:
        return link

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
            print 'Found {pgs} search page(s)'.format(pgs=pages)
            pages_to_crawl = ['{host}/discover?scope=%2F&rpp={rpp}&page={page}&query={query}&group_by=none'.format(
                query=query,
                rpp=rpp,
                page=l,
                host=config.HOST_NAME
            ) for l in range(1, pages + 1)]
            return pages_to_crawl
        else:
            print 'Can not find list of search pages'
            return []


''' Donwloads PDF file '''
def download_document(url, filename, cookies=None, tries=0):
    if tries > config.MAX_DOWNLOAD_TRIES:
        print '{start}[ FAIL ]{end} Downloading "{url}" to "{fn}" failed: tries exceeded'.format(
            url=url,
            start=Fore.RED,
            end=Style.RESET_ALL,
            fn=filename
        )
        return

    '''
    print '{start}[ INFO ]{end} Downloading {url} -> {fn}'.format(
        start=Style.BRIGHT,
        end=Style.RESET_ALL,
        url=url,
        fn=filename
    )
    '''
    cookies = cookies or {}
    r = requests.get(url, cookies=cookies, stream=True)
    if r.status_code == 200:
        with open(filename, 'wb') as f:
            for chunk in r.iter_content(chunk_size=4096):
                if chunk:
                    f.write(chunk)
        print '{start}[  OK  ]{end} Downloading "{url}" -> "{fn}" done'.format(
            url=url,
            start=Fore.GREEN,
            end=Style.RESET_ALL,
            fn=filename
        )
    else:
        print '{start}[ WARN ]{end} {url} failed due to status {status}'.format(
            url=url,
            start=Fore.YELLOW,
            end=Style.RESET_ALL,
            status=r.status_code
        )
        download_pool.spawn(download_document, url=url, filename=filename, cookies=cookies, tries=tries+1)


''' Finds PDF links on page '''
def crawl_for_pdf(url, doc_path, cookies=None, tries=0):
    if tries > config.MAX_DOWNLOAD_TRIES:
        print '{start}[ FAIL ]{end} Parsing PDF links page "{url}" for doc_path "{dp}"'.format(
            url=url,
            start=Fore.RED,
            end=Style.RESET_ALL,
            dp=doc_path
        )
        return

    cookies = cookies or {}
    r = requests.get(url, cookies=cookies)
    if r.status_code == 200:
        soup = BeautifulSoup(r.text, 'html.parser')
        links = list(set([l.attrs['href'] for l in soup.find_all('a') if ext_regex.search(l.attrs['href'])]))
        links = map(clean_link, links)
        for link in links:
            filename = None
            try:
                filename = os.path.join(doc_path, link.split('/')[-1].split('#')[0].split('?')[0].encode('utf8'))
                download_pool.spawn(download_document, url=link, filename=filename, cookies=cookies, tries=0)
            except UnicodeDecodeError as e:
                print '{start}[ WARN ]{end} Reparsing PDF page {url} -> {dp} due to "{e}"'.format(
                    url=url,
                    start=Fore.YELLOW,
                    end=Style.RESET_ALL,
                    e=e,
                    dp=doc_path
                )
                pool.spawn(crawl_for_pdf, url=url, doc_path=doc_path, cookies=cookies, tries=tries+1)
    else:
        print '{start}[ WARN ]{end} Reparsing PDF page "{url}" due to HTTP status {st}'.format(
            start=Fore.YELLOW,
            end=0,
            url=url,
            st=r.status_code
        )
        pool.spawn(crawl_for_pdf, url=url, doc_path=doc_path, cookies=cookies, tries=tries+1)

''' Finds links on given search page '''
def crawl_search(url, cookies=None):
    cookies = cookies or {}
    r = requests.get(url, cookies=cookies)
    if r.status_code == 200:
        soup = BeautifulSoup(r.text, 'html.parser')
        new_docs = [(c.text.strip(), config.HOST_NAME + c.attrs['href']) for divs in soup.find_all('div', 'artifact-title') for c in divs.children if c.name == 'a']
        print '{start}[  OK  ]{end} Parsing "{url}", found {num} document(s)'.format(
            url=url,
            num=len(new_docs),
            start=Fore.GREEN,
            end=Style.RESET_ALL
        )
        for (name, url) in new_docs:
            name = name.encode('utf8')
            name = pf_regex.sub(' ', name)
            doc_path = os.path.join(config.DOWNLOAD_DIR, name)
            if not os.path.exists(doc_path):
                os.mkdir(doc_path)
            pool.spawn(crawl_for_pdf, url=url, doc_path=doc_path, cookies=cookies, tries=0)
    else:
        print '{start}[ FAIL ]{end} Parsing "{url}"'.format(
            url=url,
            start=Fore.RED,
            end=Style.RESET_ALL
        )


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
else:
    print "Can not authenticate."
    exit(-1)
