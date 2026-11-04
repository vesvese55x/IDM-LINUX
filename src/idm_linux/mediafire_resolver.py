"""Resolve public MediaFire file pages through their ordinary download link."""
from __future__ import annotations
from html.parser import HTMLParser
from urllib.parse import urlparse, unquote
from urllib.request import Request, HTTPRedirectHandler, build_opener


def is_mediafire_url(url: str) -> bool:
    p = urlparse(url)
    host = (p.hostname or '').lower()
    return p.scheme in ('http', 'https') and (host == 'mediafire.com' or host.endswith('.mediafire.com'))


def is_mediafire_direct(url: str) -> bool:
    p = urlparse(url)
    host = (p.hostname or '').lower()
    return is_mediafire_url(url) and host.startswith('download') and host.endswith('.mediafire.com')


class _MediafireRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not is_mediafire_url(newurl):
            raise ValueError('MediaFire redirect left the trusted file-host domain')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class _DownloadLinks(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        link = a.get('href', '')
        if tag == 'a' and a.get('id') == 'downloadButton' and is_mediafire_direct(link):
            self.links.append(link)


def parse_mediafire_download(html: str):
    parser = _DownloadLinks()
    parser.feed(html)
    if not parser.links:
        raise ValueError('MediaFire public download link unavailable; browser action may be required')
    url = parser.links[0]
    name = unquote(urlparse(url).path.rsplit('/', 1)[-1])
    return url, name


def resolve_mediafire(url: str, user_agent='', cookies='', timeout=15):
    if not is_mediafire_url(url):
        raise ValueError('Not a MediaFire URL')
    if is_mediafire_direct(url):
        return url, unquote(urlparse(url).path.rsplit('/', 1)[-1])
    if not urlparse(url).path.startswith(('/file/', '/download/')):
        raise ValueError('Not a public MediaFire file page')
    headers = {'User-Agent': user_agent or 'IDM-Linux', 'Accept': 'text/html'}
    if cookies:
        headers['Cookie'] = cookies
    with build_opener(_MediafireRedirect()).open(Request(url, headers=headers), timeout=timeout) as response:
        # Do not treat CAPTCHA, login, missing files or HTML as successful downloads.
        if not is_mediafire_url(response.geturl()):
            raise ValueError('Unexpected MediaFire redirect')
        data = response.read(2 * 1024 * 1024 + 1)
        if len(data) > 2 * 1024 * 1024:
            raise ValueError('MediaFire page too large')
        return parse_mediafire_download(data.decode('utf-8', errors='replace'))
