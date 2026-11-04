"""VK metadata-only compatibility: nullable captions must not break video extraction.

No networking, authentication changes, alternate clients or DRM handling.
Loaded explicitly only by this application's VK yt-dlp subprocesses.
"""
from urllib.parse import urlsplit
from yt_dlp.extractor.vk import VKIE as _VKIE


def _repair_vk_subtitles(value):
    pending = [(value, 0)]
    visited = set()
    while pending and len(visited) < 50000:
        node, depth = pending.pop()
        if not isinstance(node, (dict, list)) or id(node) in visited or depth > 20:
            continue
        visited.add(id(node))
        if isinstance(node, dict):
            subs = node.get('subs')
            if isinstance(subs, list):
                if len(subs) > 300:
                    subs = node['subs'] = subs[:300]
                for sub in subs:
                    if not isinstance(sub, dict):
                        continue
                    if not isinstance(sub.get('lang'), str) or not sub['lang'].strip():
                        sub['lang'] = 'und'  # Unknown is not falsely advertised as English.
                    if not isinstance(sub.get('title'), str) or not sub['title'].strip():
                        try:
                            path = urlsplit(str(sub.get('url') or '')).path
                        except ValueError:
                            path = ''
                        ext = path.rsplit('.', 1)[-1].lower()
                        sub['title'] = '.' + (ext if ext in ('srt', 'vtt', 'ass', 'ssa', 'ttml') else 'srt')
            children = node.values()
        else:
            children = node
        for child in children:
            if len(pending) + len(visited) >= 50000:
                break
            if isinstance(child, (dict, list)):
                pending.append((child, depth + 1))
    return value


class VKIE(_VKIE, plugin_name='idm_nullable_subtitles'):
    def _parse_json(self, *args, **kwargs):
        return _repair_vk_subtitles(super()._parse_json(*args, **kwargs))
