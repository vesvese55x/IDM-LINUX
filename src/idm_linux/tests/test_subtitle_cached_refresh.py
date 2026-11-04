"""Engine-level regressions for asynchronous extracted caption readiness."""
from types import SimpleNamespace
import json
import unittest
from unittest.mock import patch
from idm_linux.stream_engine import StreamEngine, _probe_context_key


class Cache:
    def __init__(self):self.state=('checking',0,'');self.calls=[]
    def get(self,url,headers):self.calls.append((url,dict(headers)));return self.state


class SubtitleCachedRefreshTests(unittest.TestCase):
    def setUp(self):
        self.engine=StreamEngine(SimpleNamespace());self.cache=Cache();self.engine._subtitle_probe_cache=self.cache
        self.page='https://vk.com/video-1_2'
        self.info={'title':'Caption test','formats':[{'format_id':'p360','height':360,'url':'https://cdn.test/video.mp4','ext':'mp4','vcodec':'avc1','acodec':'aac','protocol':'https'}],
                   'subtitles':{'en':[{'url':'https://cdn.test/caption?id=1&sig=stable','ext':'vtt','http_headers':{'Referer':'https://player.test/embed','User-Agent':'context-UA','Cookie':'caption-secret=do-not-return'}}]}}
    def initial(self):
        with patch('idm_linux.stream_engine.find_ytdlp',return_value='/test/yt-dlp'),patch('idm_linux.stream_engine._run_ytdlp_probe',return_value=(self.info,'',False)) as extractor:
            result=self.engine.probe_formats(self.page,[],force_refresh=True)
        extractor.assert_called_once();return result
    def test_pending_extracted_captions_do_not_discard_video_result(self):
        first=self.initial();self.assertTrue(first['subtitle_pending']);self.assertTrue(first['formats'])
        with patch('idm_linux.stream_engine._run_ytdlp_probe',side_effect=AssertionError('Extractor must not rerun')):
            again=self.engine.probe_formats(self.page,[])
        self.assertTrue(again['formats']);self.assertTrue(again['subtitle_pending'])
    def test_cached_pending_becomes_ready_without_new_signed_url(self):
        self.initial();self.cache.state=('ok',123,'srt')
        with patch('idm_linux.stream_engine._run_ytdlp_probe',side_effect=AssertionError('Extractor must not rerun')):
            again=self.engine.probe_formats(self.page,[])
        subtitle=next(f for f in again['formats'] if f['delivery']=='subs')
        self.assertEqual(subtitle['subtitle_state'],'ready');self.assertEqual(subtitle['filesize'],123)
        self.assertEqual(subtitle['ext'],'srt');self.assertIn('(SRT)',subtitle['label']);self.assertFalse(again['subtitle_pending'])
        self.assertEqual(self.cache.calls[-1][1]['Referer'],'https://player.test/embed')
        self.assertEqual(self.cache.calls[-1][1]['User-Agent'],'context-UA')
    def test_internal_headers_are_not_returned_to_client(self):
        first=self.initial();again=self.engine.probe_formats(self.page,[])
        for result in [first,again]:
            self.assertNotIn('_subtitle_probe_context',result)
            self.assertNotIn('subtitle_probe_headers',json.dumps(result))
            self.assertNotIn('caption-secret',json.dumps(result))
    def test_failed_caption_is_removed_without_losing_video(self):
        self.initial();self.cache.state=('bad',0,'');again=self.engine.probe_formats(self.page,[])
        self.assertTrue(again['formats']);self.assertFalse(any(f['delivery']=='subs' for f in again['formats']))
    def test_unknown_is_not_marked_ready(self):
        self.initial();self.cache.state=('unknown',0,'');again=self.engine.probe_formats(self.page,[])
        self.assertEqual(next(f for f in again['formats'] if f['delivery']=='subs')['subtitle_state'],'unavailable')
    def test_real_background_path_finishes_and_does_not_restart_extractor(self):
        class ImmediateThread:
            def __init__(self,target,**kwargs):self.target=target
            def start(self):self.target()
        with patch('idm_linux.stream_engine.find_ytdlp',return_value='/test/yt-dlp'),patch('idm_linux.stream_engine._run_ytdlp_probe',return_value=(self.info,'',False)) as extractor,patch('idm_linux.stream_engine.threading.Thread',ImmediateThread),patch('idm_linux.stream_engine._notify_probe_done'):
            first=self.engine.probe_formats(self.page,[])
            self.assertTrue(first['ytdlp_pending'])
            second=self.engine.probe_formats(self.page,[])
            self.assertFalse(second['ytdlp_pending']);self.assertTrue(second['subtitle_pending'])
            self.cache.state=('ok',123,'vtt')
            third=self.engine.probe_formats(self.page,[])
            self.assertFalse(third['subtitle_pending']);extractor.assert_called_once()
    def test_new_manifest_caption_invalidates_same_count_bucket(self):
        a=[{'url':'https://cdn.test/master.m3u8','manifestText':'#EXTM3U\n'}]
        b=[dict(a[0],manifestText='#EXTM3U\n#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="s",NAME="English",URI="en.vtt"\n')]
        self.assertNotEqual(_probe_context_key(self.page,a),_probe_context_key(self.page,b))
    def test_cookie_and_frame_context_do_not_share_cache_keys(self):
        a=_probe_context_key(self.page,[],'account=one','https://frame.one','ua')
        for args in [('account=two','https://frame.one','ua'),('account=one','https://frame.two','ua'),('account=one','https://frame.one','other-ua')]:
            self.assertNotEqual(a,_probe_context_key(self.page,[],*args))
    def test_new_caption_invalidates_same_count_bucket(self):
        first=[{'url':'https://cdn.test/video.mp4','mime':'video/mp4'}]
        second=first+[{'url':'https://cdn.test/en.vtt','mime':'text/vtt'}]
        self.assertNotEqual(_probe_context_key(self.page,first),_probe_context_key(self.page,second))
    def test_source_cookie_context_changes_key(self):
        a=[{'url':'https://cdn.test/en.vtt','mime':'text/vtt','cookie_header':'frame=one'}]
        b=[dict(a[0],cookie_header='frame=two')]
        self.assertNotEqual(_probe_context_key(self.page,a),_probe_context_key(self.page,b))

if __name__=='__main__':unittest.main()
