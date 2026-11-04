"""Real local HTTP subtitle delivery + bounded asynchronous discovery regressions."""
import json
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from idm_linux.subtitle_probe_cache import SubtitleProbeCache
from idm_linux.stream_engine import _subtitle_options, ActiveStreamJob, StreamTicket
from idm_linux.hls_streamer import fetch_subtitle_probe, fetch_subtitle_bytes_smart, normalize_caption_payload

VTT = b'WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nMerhaba dunya\n'
JSON3 = json.dumps({'events':[{'tStartMs':1000,'dDurationMs':2200,'segs':[{'utf8':'Merhaba '},{'utf8':'dunya'}]}]}).encode()

class SubtitleProbePipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_): pass
            def do_GET(self):
                cls.requests.append((self.path,self.headers.get('Referer'),self.headers.get('Cookie')))
                if self.path=='/locked':
                    self.send_response(403);self.end_headers();return
                if self.path=='/slow':time.sleep(.3)
                body={ '/vtt':VTT, '/chunked':VTT, '/slow':VTT, '/json3':JSON3,
                       '/playlist':b'#EXTM3U\n#EXT-X-TARGETDURATION:2\n#EXTINF:2,\nvtt\n#EXT-X-ENDLIST\n',
                       '/html':b'<html>not subtitles</html>'}.get(self.path,VTT)
                self.send_response(200)
                if self.path!='/chunked':self.send_header('Content-Length',str(len(body)))
                self.end_headers();self.wfile.write(body)
        cls.requests=[];cls.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
        cls.base='http://127.0.0.1:'+str(cls.server.server_address[1])
    @classmethod
    def tearDownClass(cls):cls.server.shutdown();cls.server.server_close();cls.thread.join(2)
    def wait_cache(self,c,url,headers=None):
        deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            value=c.get(url,headers or {})
            if value[0] not in ('checking','deferred'):return value
            time.sleep(.01)
        self.fail('cache did not settle')
    def test_network_check_does_not_block_first_response(self):
        c=SubtitleProbeCache();t=time.monotonic()
        self.assertEqual(c.get(self.base+'/slow',{})[0],'checking')
        self.assertLess(time.monotonic()-t,.15)
        self.assertEqual(self.wait_cache(c,self.base+'/slow')[0],'ok')
    def test_many_pollers_share_one_request(self):
        calls=[];gate=threading.Event()
        def probe(*args):calls.append(args);gate.wait(2);return ('ok',50,'vtt')
        c=SubtitleProbeCache(probe=probe)
        for _ in range(30):c.get('https://example.test/caption',{})
        gate.set();self.assertEqual(self.wait_cache(c,'https://example.test/caption')[0],'ok')
        self.assertEqual(len(calls),1)
    def test_headers_are_part_of_cache_identity(self):
        calls=[]
        c=SubtitleProbeCache(probe=lambda u,h,t:(calls.append(h) or ('ok',50,'vtt')))
        self.wait_cache(c,'https://example.test/caption',{'Referer':'https://one.test'})
        self.wait_cache(c,'https://example.test/caption',{'Referer':'https://two.test'})
        self.assertEqual(len(calls),2)
    def test_inflight_capacity_is_bounded(self):
        gate=threading.Event()
        c=SubtitleProbeCache(probe=lambda *args:(gate.wait(2) or ('unknown',0,'')),workers=1,capacity=3)
        for i in range(30):c.get('https://example.test/'+str(i),{})
        self.assertLessEqual(len(c.entries),3);self.assertLessEqual(c.queue.qsize(),3);gate.set()
    def test_all_25_tracks_survive_without_blocking_video_probe(self):
        streams=[{'url':self.base+'/vtt?lang='+str(i),'mime':'text/vtt'} for i in range(25)]
        c=SubtitleProbeCache(probe=lambda *args:('ok',50,'vtt'))
        opts=_subtitle_options(streams,self.base,self.base,probe_cache=c)
        self.assertEqual(len(opts),25)
    def test_unknown_is_not_marked_ready(self):
        class Cache:
            def get(self,*args):return ('unknown',0,'')
        opts=_subtitle_options([{'url':self.base+'/vtt','mime':'text/vtt'}],self.base,self.base,probe_cache=Cache())
        self.assertEqual(opts[0].subtitle_state,'unavailable');self.assertFalse(opts[0].filesize_exact)
    def test_html_is_rejected(self):self.assertEqual(fetch_subtitle_probe(self.base+'/html',{})[0],'bad')
    def test_authorization_failure_does_not_strip_headers_or_retry(self):
        before=len(self.requests)
        self.assertEqual(fetch_subtitle_probe(self.base+'/locked',{'Cookie':'qa=1'})[0],'unknown')
        self.assertEqual(len(self.requests)-before,1)
    def test_unknown_length_is_not_claimed_as_exact_prefix_length(self):
        status,size,kind=fetch_subtitle_probe(self.base+'/chunked',{})
        self.assertEqual((status,size,kind),('ok',0,'vtt'))
    def test_hls_subtitle_manifest_is_not_rejected_as_fake(self):
        self.assertEqual(fetch_subtitle_probe(self.base+'/playlist',{}),('ok',0,'vtt'))
    def test_real_http_json3_is_converted_to_valid_vtt(self):
        raw=fetch_subtitle_bytes_smart(self.base+'/json3',{})
        self.assertTrue(raw.startswith(b'WEBVTT'));self.assertIn(b'00:00:01.000 --> 00:00:03.200',raw)
    def test_srv_xml_caption_conversion(self):
        for raw in [b'<transcript><text start="1" dur="2">Hi</text></transcript>',b'<timedtext><body><p t="1000" d="2000"><s>Hi</s></p></body></timedtext>']:
            self.assertIn(b'00:00:01.000 --> 00:00:03.000',normalize_caption_payload(raw))
    def test_error_json_does_not_become_fake_vtt(self):
        raw=b'{"error":"login required"}';self.assertEqual(normalize_caption_payload(raw),raw)
    def test_real_http_subtitle_job_preserves_format_and_text(self):
        with tempfile.TemporaryDirectory() as d:
            job=ActiveStreamJob(StreamTicket(ticket_id='http-caption',source_url=self.base+'/json3',filename='qa.vtt',mode='subs'),Path(d))
            self.assertTrue(job._run_subtitle_record());self.assertTrue(job.completed)
            self.assertEqual(job.output_file.suffix,'.vtt');self.assertIn('Merhaba dunya',job.output_file.read_text())
    def test_source_bound_cookies_and_iframe_headers(self):
        url=self.base+'/vtt';ctx={'url':url,'mime':'text/vtt','referer':self.base+'/player','cookie_header':'qa=correct','user_agent':'qa-ua'}
        with patch('idm_linux.hls_streamer.fetch_subtitle_probe',return_value=('ok',50,'vtt')) as probe:
            _subtitle_options([ctx],self.base+'/film',self.base+'/film',cookies='wrong=merged')
        self.assertEqual(probe.call_args.args[1]['Cookie'],'qa=correct')
        self.assertEqual(probe.call_args.args[1]['Referer'],self.base+'/player')
    def test_remote_url_is_replaced_by_captured_local_text_not_duplicated(self):
        remote={'url':'https://www.youtube.com/api/timedtext?v=qa&lang=tr&fmt=vtt','mime':'text/vtt'}
        vault={'url':self.base+'/vtt','original_url':'https://www.youtube.com/api/timedtext?v=qa&lang=tr&fmt=json3','mime':'text/vtt'}
        opts=_subtitle_options([remote,vault,remote],self.base,self.base,validate=False)
        self.assertEqual(len(opts),1);self.assertEqual(opts[0].direct_url,vault['url'])

    def test_hls_relative_uri_uses_manifest_parent_directory(self):
        from idm_linux.stream_engine import parse_hls_subtitles
        text='#EXTM3U\n#EXT-X-MEDIA:TYPE=SUBTITLES,LANGUAGE="tr",URI="subs/tr.m3u8"\n'
        self.assertEqual(parse_hls_subtitles(text,'https://cdn.test/path/master.m3u8'),[('lang:tr','https://cdn.test/path/subs/tr.m3u8')])

    def test_dash_namespaces_and_nested_baseurl_preserve_language(self):
        from idm_linux.stream_engine import parse_dash_subtitles
        text='<MPD xmlns="urn:mpeg:dash:schema:mpd:2011"><BaseURL>assets/</BaseURL><Period><BaseURL>part/</BaseURL><AdaptationSet mimeType="application/ttml+xml" lang="tr"><Representation><BaseURL>tr.ttml</BaseURL></Representation></AdaptationSet></Period></MPD>'
        self.assertEqual(parse_dash_subtitles(text,'https://cdn.test/manifest.mpd'),[('tr','https://cdn.test/assets/part/tr.ttml')])

    def test_missing_hls_caption_segment_does_not_return_partial_success(self):
        from idm_linux.hls_streamer import assemble_subtitle_text
        text='#EXTM3U\n#EXT-X-TARGETDURATION:2\n#EXTINF:2,\nvtt\n#EXTINF:2,\nlocked\n#EXT-X-ENDLIST\n'
        with self.assertRaisesRegex(RuntimeError,'eksik'):
            assemble_subtitle_text(self.base+'/master',{},initial_text=text)

    def test_html_hls_caption_segment_is_failure(self):
        from idm_linux.hls_streamer import assemble_subtitle_text
        text='#EXTM3U\n#EXT-X-TARGETDURATION:2\n#EXTINF:2,\nvtt\n#EXTINF:2,\nhtml\n#EXT-X-ENDLIST\n'
        with self.assertRaisesRegex(RuntimeError,'eksik'):
            assemble_subtitle_text(self.base+'/master',{},initial_text=text)

    def test_external_ok_vk_extractor_subtitles_enter_shared_validation(self):
        from idm_linux.stream_engine import _extracted_subtitle_streams
        for page in ['https://ok.ru/video/123','https://vkvideo.ru/video-1_2']:
            info={'subtitles':{'tr':[{'url':self.base+'/json3','ext':'json3'},{'url':self.base+'/vtt','ext':'vtt'}]},'automatic_captions':{'tr':[{'url':self.base+'/html'}]}}
            streams=_extracted_subtitle_streams(info,page)
            self.assertEqual(len(streams),1);self.assertEqual(streams[0]['url'],self.base+'/vtt')
            self.assertEqual(streams[0]['referer'],page)

    def test_vk_public_alias_preserves_id_and_query(self):
        from idm_linux.stream_engine import _extractor_page_url
        self.assertEqual(_extractor_page_url('https://vkvideo.ru/video-123_456?list=public'),'https://vk.com/video-123_456?list=public')
        self.assertEqual(_extractor_page_url('https://evil.test/video-123_456'),'https://evil.test/video-123_456')
        self.assertEqual(_extractor_page_url('https://vkvideo.ru/@channel/playlists'),'https://vkvideo.ru/@channel/playlists')

    def test_thumbnail_vtt_is_not_dialogue_subtitle(self):
        from idm_linux.hls_streamer import looks_like_subtitle_bytes
        self.assertFalse(looks_like_subtitle_bytes(b'WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nhttps://cdn.test/frame.webp#xywh=0,0,100,100\n'))

if __name__=='__main__':unittest.main()
