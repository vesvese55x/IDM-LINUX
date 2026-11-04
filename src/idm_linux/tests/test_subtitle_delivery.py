"""Subtitle identity and real-format delivery regressions; no external sites required."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from idm_linux.stream_engine import ActiveStreamJob, StreamTicket, _norm_sub_dedup_key, _subtitle_options

VTT='WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nMerhaba dünya\n'

class SubtitleDeliveryTests(unittest.TestCase):
    def run_download(self, body):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        job=ActiveStreamJob(StreamTicket(ticket_id='test',source_url='https://www.youtube.com/watch?v=test',filename='captions.srt',mode='ytdlp',sub_lang='en-US'),Path(temp.name))
        seen=[]
        class Process:
            def __init__(self,command,**kwargs):
                seen.extend(command);Path(command[command.index('-o')+1]+'.en-US.vtt').write_text(body)
            def poll(self):return 0
            def wait(self,**kwargs):return 0
        with patch('idm_linux.stream_engine.find_ytdlp',return_value='/test/yt-dlp'),patch('idm_linux.stream_engine.subprocess.Popen',Process):
            ok=job._run_ytdlp_record()
        return job,seen,ok

    def test_auto_captions_are_requested_and_vtt_is_really_converted(self):
        job,cmd,ok=self.run_download(VTT)
        self.assertTrue(ok);self.assertIn('--write-auto-subs',cmd);self.assertIn('--write-subs',cmd)
        self.assertEqual(job.output_file.suffix,'.srt');text=job.output_file.read_text()
        self.assertNotIn('WEBVTT',text);self.assertIn('00:00:01,000 --> 00:00:03,000',text);self.assertIn('Merhaba dünya',text)

    def test_empty_or_html_subtitle_is_not_success(self):
        for body in ('','<html>Authorization Required</html>','WEBVTT\n\n'):
            with self.subTest(body=body):
                job,_,ok=self.run_download(body);self.assertFalse(ok);self.assertFalse(job.completed)

    def test_language_and_video_identity_survive_dedup(self):
        base='https://www.youtube.com/api/timedtext?'
        self.assertNotEqual(_norm_sub_dedup_key(base+'v=one&lang=tr'),_norm_sub_dedup_key(base+'v=one&lang=en'))
        self.assertNotEqual(_norm_sub_dedup_key(base+'v=one&lang=en'),_norm_sub_dedup_key(base+'v=two&lang=en'))
        self.assertEqual(_norm_sub_dedup_key(base+'v=one&lang=en&expire=10&sig=old'),_norm_sub_dedup_key(base+'sig=new&lang=en&v=one&expire=20'))
        self.assertNotEqual(_norm_sub_dedup_key('https://example.test/sub.php?id=1'),_norm_sub_dedup_key('https://example.test/sub.php?id=2'))

    def test_late_tracks_and_multiple_timedtext_languages_are_listed(self):
        streams=[{'url':f'https://example.test/video{i}.mp4','mime':'video/mp4'} for i in range(55)]
        streams += [{'url':'https://www.youtube.com/api/timedtext?v=one&lang='+lang,'mime':'text/vtt','sub_label':'lang:'+lang} for lang in ('tr','en')]
        options=_subtitle_options(streams,'https://example.test/player','https://example.test/player',validate=False)
        self.assertEqual(len(options),2)

class SubtitleFrameContextTests(unittest.TestCase):
    def test_iframe_referer_and_fresh_signed_url_survive(self):
        frame='https://player.example.test/embed/123'
        streams=[{'url':'https://cdn.example.test/tr.vtt?sig='+sig,'mime':'text/vtt','referer':frame,'origin':'https://player.example.test'} for sig in ('old','new')]
        with patch('idm_linux.hls_streamer.fetch_subtitle_probe',return_value=('ok',70,'vtt')) as probe:
            options=_subtitle_options(streams,'https://film.example.test/movie','https://film.example.test/movie')
        self.assertEqual(len(options),1);self.assertTrue(options[0].direct_url.endswith('sig=new'))
        self.assertEqual(options[0].stream_referer,frame);self.assertEqual(probe.call_args.args[1]['Referer'],frame)

class SubtitleAuthenticationTests(unittest.TestCase):
    def test_auth_gate_does_not_trigger_alternate_clients(self):
        with tempfile.TemporaryDirectory() as d:
            job=ActiveStreamJob(StreamTicket(ticket_id='auth',source_url='https://www.youtube.com/watch?v=test',filename='captions.srt',mode='ytdlp',sub_lang='en'),Path(d))
            def rejected(**kwargs):
                job.error_msg='Sign in to confirm you are not a bot';return False
            with patch.object(job,'_run_ytdlp_record',side_effect=rejected) as attempt:
                self.assertFalse(job._run_ytdlp_record_resilient());self.assertEqual(attempt.call_count,1)

if __name__=='__main__':unittest.main()
