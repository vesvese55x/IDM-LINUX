"""Remote desktop regressions: don't lose torrent tickets or rely on systemd."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from idm_linux import daemon as dm

class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.state=SimpleNamespace(running=True,stream_engine=SimpleNamespace(active_job_count=Mock(return_value=0)),torrent_bridge=SimpleNamespace(list_active_summary=Mock(return_value=[]),shutdown_all=Mock()),playlist_manager=SimpleNamespace(list_batches=Mock(return_value=[]),shutdown_all=Mock()))
        self.ed=patch.object(dm,'ed2k_list_sessions',return_value=[]).start()
        self.addCleanup(patch.stopall)
    def test_idle_is_idle(self):
        self.assertFalse(dm._daemon_has_active_transfers(self.state))
    def test_stream_blocks_recycle(self):
        self.state.stream_engine.active_job_count.return_value=1
        self.assertTrue(dm._daemon_has_active_transfers(self.state))
    def test_torrent_active_waiting_paused_and_unknown_are_preserved(self):
        for status in ['active','preparing','waiting','paused',None,'new-state']:
            with self.subTest(status=status):
                self.state.torrent_bridge.list_active_summary.return_value=[{'status':status}]
                self.assertTrue(dm._daemon_has_active_transfers(self.state))
    def test_terminal_sessions_allow_recycle(self):
        self.state.torrent_bridge.list_active_summary.return_value=[{'status':'complete'},{'status':'error'}]
        self.ed.return_value=[{'status':'removed'}]
        self.assertFalse(dm._daemon_has_active_transfers(self.state))
    def test_ed2k_is_preserved(self):
        self.ed.return_value=[{'status':'active'}]
        self.assertTrue(dm._daemon_has_active_transfers(self.state))
    def test_playlist_queue_and_pause_are_preserved(self):
        for status in ['queued','downloading','paused']:
            self.state.playlist_manager.list_batches.return_value=[{'done':False,'entries':[{'status':status}]}]
            self.assertTrue(dm._daemon_has_active_transfers(self.state))
    def test_finished_playlist_allows_recycle(self):
        self.state.playlist_manager.list_batches.return_value=[{'done':True,'entries':[]}]
        self.assertFalse(dm._daemon_has_active_transfers(self.state))
    def test_query_failure_is_not_idle(self):
        self.state.torrent_bridge.list_active_summary.side_effect=RuntimeError('status unavailable')
        self.assertTrue(dm._daemon_has_active_transfers(self.state))
    def test_restart_rechecks_busy_state_before_mutation(self):
        self.state.torrent_bridge.list_active_summary.return_value=[{'status':'active'}]
        with patch.object(dm.os,'execvpe') as execute:
            dm._self_restart_daemon(self.state)
        execute.assert_not_called();self.assertTrue(self.state.running)
        self.state.torrent_bridge.shutdown_all.assert_not_called()
    def test_idle_restart_uses_current_interpreter_and_environment(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(dm,'get_cache_dir',return_value=Path(tmp)),patch.object(dm.threading,'Thread'),patch.object(dm.os,'execvpe') as execute:
            dm._self_restart_daemon(self.state)
            args=execute.call_args.args
            self.assertEqual(args[0],dm.sys.executable)
            self.assertEqual(args[1],[dm.sys.executable,'-m','idm_linux.cli','daemon-run'])
            self.assertEqual(args[2],dict(dm.os.environ))
    def test_failed_exec_keeps_unsupervised_bridge_running(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(dm,'get_cache_dir',return_value=Path(tmp)),patch.object(dm.threading,'Thread'),patch.object(dm.os,'execvpe',side_effect=OSError('exec failed')):
            dm._self_restart_daemon(self.state)
        self.assertTrue(self.state.running)


class LiveMuxOrderTests(unittest.TestCase):
    def make_job(self):
        from idm_linux.stream_engine import ActiveStreamJob,StreamTicket
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        return ActiveStreamJob(StreamTicket(ticket_id='mux-order',source_url='https://ok.ru/video/123',filename='test.mp4',mode='fast_mux',mux_video_url='https://cdn.example/video.mp4',mux_audio_url='https://cdn.example/audio.m4a'),Path(temp.name))
    def test_http_mux_precedes_audio_prebuffer(self):
        job=self.make_job()
        with patch('idm_linux.stream_engine.find_ytdlp',return_value=None),patch('idm_linux.stream_engine.shutil.which',return_value='/usr/bin/ffmpeg'),patch.object(job,'_run_prebuilt_urls_ffmpeg_mux',return_value=True) as live,patch.object(job,'_run_live_mux_record') as prebuffer:
            job._run_worker()
        live.assert_called_once();prebuffer.assert_not_called()
    def test_existing_mux_fallback_is_retained(self):
        job=self.make_job()
        with patch('idm_linux.stream_engine.find_ytdlp',return_value=None),patch('idm_linux.stream_engine.shutil.which',return_value='/usr/bin/ffmpeg'),patch.object(job,'_run_prebuilt_urls_ffmpeg_mux',return_value=False),patch.object(job,'_run_live_mux_record',return_value=True) as legacy:
            job._run_worker()
        legacy.assert_called_once()
    def test_audio_and_video_are_each_mapped_once(self):
        import os
        job=self.make_job();commands=[]
        class Process:
            def __init__(self,cmd,**kw):
                commands.append(cmd);rd,wr=os.pipe();os.write(wr,b'x'*5000);os.close(wr);self.stdout=os.fdopen(rd,'rb')
            def wait(self,**kw):return 0
        with patch('idm_linux.stream_engine.subprocess.Popen',Process),patch.object(job,'_idle_watchdog',return_value=Mock()):
            self.assertTrue(job._run_prebuilt_urls_ffmpeg_mux('/test/ffmpeg'))
        cmd=commands[0];self.assertEqual(cmd.count('-map'),2);self.assertEqual(cmd.count('0:v:0'),1);self.assertEqual(cmd.count('1:a:0'),1)


class AvailabilityTests(unittest.TestCase):
    def setUp(self):
        from idm_linux import stream_engine as se
        self.se=se
        self.cache=patch.dict(se._MEDIA_AVAILABLE_AT,{},clear=True);self.cache.start();self.addCleanup(self.cache.stop)
        clock_patch=patch.object(se.time,'time',return_value=100.0);self.clock=clock_patch.start();self.addCleanup(clock_patch.stop)
    def job(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        return self.se.ActiveStreamJob(self.se.StreamTicket(ticket_id='availability',source_url='https://youtube.com/watch?v=test',filename='a.mp4',mode='fast_mux',mux_video_url='https://cdn.example/v'),Path(temp.name))
    def test_formats_and_requested_formats_retain_not_before(self):
        self.se._remember_media_availability({'formats':[{'url':'https://cdn.example/v','available_at':104}],'requested_formats':[{'url':'https://cdn.example/a','available_at':106}]})
        self.assertEqual(self.se.media_availability_delay('https://cdn.example/v','https://cdn.example/a'),6)
    def test_expired_and_malformed_deadlines_are_not_waited(self):
        for value in [0,99,None,'bad',float('inf'),float('nan')]:
            self.se._remember_media_availability({'url':'https://cdn.example/v','available_at':value})
        self.assertEqual(self.se.media_availability_delay('https://cdn.example/v'),0)
    def test_metadata_cache_is_bounded_and_expired_entries_are_purged(self):
        self.se._remember_media_availability({'formats':[{'url':f'https://cdn.example/{n}','available_at':110} for n in range(500)]})
        self.assertEqual(len(self.se._MEDIA_AVAILABLE_AT),300)
        self.clock.return_value=111;self.se._remember_media_availability({})
        self.assertEqual(len(self.se._MEDIA_AVAILABLE_AT),0)
    def test_wait_is_cancellable_before_any_ffmpeg_request(self):
        job=self.job();self.se._remember_media_availability({'url':job.ticket.mux_video_url,'available_at':106})
        with patch.object(job.stop_event,'wait',return_value=True) as wait,patch.object(self.se.subprocess,'Popen') as start:
            self.assertFalse(job._run_prebuilt_urls_ffmpeg_mux('/test/ffmpeg'))
        wait.assert_called_once_with(6);start.assert_not_called()
    def test_elapsed_deadline_has_no_extra_delay(self):
        job=self.job();self.se._remember_media_availability({'url':job.ticket.mux_video_url,'available_at':106});self.clock.return_value=107
        with patch.object(job.stop_event,'wait') as wait:
            self.assertTrue(job._wait_for_media_availability(job.ticket.mux_video_url))
        wait.assert_not_called()
    def test_resolver_waits_before_head_or_ffmpeg_handoff(self):
        job=self.job();info={'requested_formats':[{'url':'https://cdn.example/v','available_at':106}]}
        with patch.object(self.se.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=__import__('json').dumps(info))),patch.object(job,'_wait_for_media_availability',return_value=False) as wait,patch.object(self.se,'probe_url_is_hls') as head:
            self.assertFalse(job._run_ytdlp_resolved_live('/test/yt-dlp','/test/ffmpeg',None))
        wait.assert_called_once_with('https://cdn.example/v');head.assert_not_called()


class RealUnsupervisedExecTests(unittest.TestCase):
    def test_real_exec_preserves_pid_and_releases_listener_without_systemd(self):
        import json,os,subprocess,sys
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);stub=root/'stub'/'idm_linux';stub.mkdir(parents=True)
            (stub/'__init__.py').write_text('')
            (stub/'cli.py').write_text('''import os,json,socket,sys
from pathlib import Path
root=Path(os.environ['IDM_EXEC_TEST_ROOT']);before=json.loads((root/'before.json').read_text())
assert os.getpid()==before['pid']
with socket.socket() as s:s.bind(('127.0.0.1',before['port']))
(root/'after.json').write_text(json.dumps({'pid':os.getpid(),'args':sys.argv[1:],'listener_rebound':True}))
''')
            child='''import os,json,socket
from pathlib import Path
from types import SimpleNamespace
from idm_linux import daemon as dm
root=Path(os.environ['IDM_EXEC_TEST_ROOT']);listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen()
(root/'before.json').write_text(json.dumps({'pid':os.getpid(),'port':listener.getsockname()[1]}))
os.environ['PYTHONPATH']=str(root/'stub')
state=SimpleNamespace(running=True,stream_engine=SimpleNamespace(active_job_count=lambda:0),torrent_bridge=SimpleNamespace(list_active_summary=lambda:[],shutdown_all=lambda:None),playlist_manager=SimpleNamespace(list_batches=lambda:[],shutdown_all=lambda:None))
dm._self_restart_daemon(state)
raise RuntimeError('exec returned unexpectedly')
'''
            env={**os.environ,'HOME':temp,'XDG_CONFIG_HOME':str(root/'config'),'XDG_CACHE_HOME':str(root/'cache'),'IDM_EXEC_TEST_ROOT':temp,'PYTHONPATH':str(Path(__file__).resolve().parents[2])}
            r=subprocess.run([sys.executable,'-c',child],env=env,capture_output=True,text=True,timeout=15)
            self.assertEqual(r.returncode,0,r.stderr)
            after=json.loads((root/'after.json').read_text());self.assertEqual(after['args'],['daemon-run']);self.assertTrue(after['listener_rebound'])


class RemuxLengthTests(unittest.TestCase):
    def test_remux_estimate_is_not_an_exact_http_length(self):
        from idm_linux.stream_engine import StreamEngine,ActiveStreamJob
        from idm_linux.config import IdmLinuxConfig
        with tempfile.TemporaryDirectory() as tmp,patch('idm_linux.stream_engine.get_cache_dir',return_value=Path(tmp)),patch.object(ActiveStreamJob,'ensure_started'):
            engine=StreamEngine(IdmLinuxConfig())
            for kwargs in [{'mux_video_url':'https://cdn.example/v','mux_audio_url':'https://cdn.example/a'},{'format_selector':'bestvideo+bestaudio'}]:
                ticket=engine.create_ticket(source_url='https://youtube.com/watch?v=test',filename='v.mp4',mode='fast_mux',estimated_size=123456,size_exact=True,**kwargs)
                self.assertFalse(ticket.size_exact);self.assertEqual(ticket.estimated_size,123456)
    def test_unchanged_single_file_length_remains_exact(self):
        from idm_linux.stream_engine import StreamEngine,ActiveStreamJob
        from idm_linux.config import IdmLinuxConfig
        with tempfile.TemporaryDirectory() as tmp,patch('idm_linux.stream_engine.get_cache_dir',return_value=Path(tmp)),patch.object(ActiveStreamJob,'ensure_started'):
            ticket=StreamEngine(IdmLinuxConfig()).create_ticket(source_url='https://cdn.example/v.mp4',filename='v.mp4',mode='relay',estimated_size=123456,size_exact=True)
            self.assertTrue(ticket.size_exact)

if __name__=='__main__':unittest.main()
