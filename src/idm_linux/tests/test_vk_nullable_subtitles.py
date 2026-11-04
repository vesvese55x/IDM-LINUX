"""Deterministic nullable-VK metadata regressions; does not require yt-dlp installed."""
import importlib.util
import json
from pathlib import Path
from types import ModuleType, SimpleNamespace
import sys
import unittest
from unittest.mock import patch
from idm_linux.stream_engine import _ytdlp_compat_args, _subtitle_options, _run_ytdlp_probe

PLUGIN = Path(__file__).parents[1]/'extractor_plugins/idm_vk_compat/yt_dlp_plugins/extractor/vk_nullable_subtitles.py'


def load_plugin():
    class Base:
        def __init_subclass__(cls, plugin_name=None, **kwargs):
            cls.test_plugin_name=plugin_name
        def _parse_json(self, data, *args, **kwargs):return data
    vk=ModuleType('yt_dlp.extractor.vk');vk.VKIE=Base
    modules={'yt_dlp':ModuleType('yt_dlp'),'yt_dlp.extractor':ModuleType('yt_dlp.extractor'),'yt_dlp.extractor.vk':vk}
    with patch.dict(sys.modules,modules):
        spec=importlib.util.spec_from_file_location('idm_test_vk_compat',PLUGIN);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


class VkNullableSubtitleTests(unittest.TestCase):
    def setUp(self):self.plugin=load_plugin()
    def test_nullable_metadata_does_not_invent_english(self):
        value={'params':[{'subs':[{'lang':None,'title':None,'url':'https://cdn.test/ru.vtt'}]}]}
        self.plugin._repair_vk_subtitles(value);sub=value['params'][0]['subs'][0]
        self.assertEqual(sub['lang'],'und');self.assertEqual(sub['title'],'.vtt')
        self.assertEqual(sub['url'],'https://cdn.test/ru.vtt')
    def test_valid_metadata_is_preserved(self):
        sub={'lang':'tr','title':'original.ass','url':'https://cdn.test/1?sig=private'};value={'subs':[dict(sub)]}
        self.plugin._repair_vk_subtitles(value);self.assertEqual(value['subs'][0],sub)
    def test_missing_empty_and_invalid_types(self):
        for fields in [{},{'lang':'','title':''},{'lang':False,'title':[]},{'lang':None,'title':None,'url':'http://[invalid'}]:
            data={'subs':[fields]};self.plugin._repair_vk_subtitles(data)
            self.assertEqual(data['subs'][0]['lang'],'und');self.assertIsInstance(data['subs'][0]['title'],str)
    def test_non_caption_json_and_cycles_are_safe(self):
        for data in [None,123,'text',{'subs':None},{'subs':['not-track',None]},[]]:
            self.assertIs(self.plugin._repair_vk_subtitles(data),data)
        cycle={};cycle['self']=cycle;self.assertIs(self.plugin._repair_vk_subtitles(cycle),cycle)
    def test_plugin_parse_hook_preserves_video_formats(self):
        obj={'player':{'params':[{'subs':[{'lang':None,'title':None,'url':'https://cdn.test/sub'}],'url720':'https://cdn.test/video.mp4'}]}}
        result=self.plugin.VKIE()._parse_json(obj,'video-id')
        self.assertEqual(result['player']['params'][0]['url720'],'https://cdn.test/video.mp4')
        self.assertEqual(self.plugin.VKIE.test_plugin_name,'idm_nullable_subtitles')
    def test_caption_count_is_bounded_before_upstream_loop(self):
        obj={'subs':[{'lang':None,'title':None} for _ in range(1000)]};self.plugin._repair_vk_subtitles(obj)
        self.assertEqual(len(obj['subs']),300);self.assertTrue(all(s['lang']=='und' for s in obj['subs']))
    def test_plugin_is_scoped_to_actual_vk_hosts(self):
        for host in ['vk.com','m.vkvideo.ru','vk.ru','vkontakte.ru']:
            self.assertEqual(_ytdlp_compat_args('https://'+host+'/video-1_2')[0],'--plugin-dirs')
        for url in ['https://youtube.com/watch?v=vk.com','https://evil.test/?next=vk.ru','https://vk.com.evil.test/video-1_2','https://ok.ru/video/123']:
            self.assertEqual(_ytdlp_compat_args(url),[])
    def test_probe_command_actually_includes_plugin_without_auth_changes(self):
        response=SimpleNamespace(returncode=0,stdout=json.dumps({'formats':[]}),stderr='')
        with patch('idm_linux.stream_engine.subprocess.run',return_value=response) as run:
            _run_ytdlp_probe('/test/yt-dlp','https://vk.com/video-1_2',None)
        command=run.call_args.args[0];self.assertIn('--plugin-dirs',command);self.assertNotIn('--cookies',command)
        self.assertNotIn('--extractor-args',command)
    def test_iso_caption_label_is_readable_without_overwriting_names(self):
        for label,expected in [('en','English'),('tr','Türkçe'),('Original label','Original label')]:
            formats=_subtitle_options([{'url':'https://cdn.test/cap.vtt','mime':'text/vtt','sub_label':label}],'','',validate=False)
            self.assertIn(expected,formats[0].label)

if __name__=='__main__':unittest.main()
