"""Language enumeration regressions. Fixtures model the 25-track live QA video.

These are unit tests, not proof of a successful live YouTube download.
"""
import unittest
from idm_linux.stream_engine import _youtube_lang_options

LANGS = ['ar', 'bn', 'de', 'es', 'fr', 'hi', 'id', 'it', 'ja', 'ko', 'ml', 'mr',
         'pa', 'pl', 'pt', 'ru', 'ta', 'te', 'th', 'tr', 'vi', 'zh', 'zh-Hans', 'zh-Hant', 'en']
PAGE = 'https://www.youtube.com/watch?v=1WEAJ-DFkHE'


class YouTubeLanguageDetectionTests(unittest.TestCase):
    def audio(self, langs):
        return {'formats': [{'language':lang,'vcodec':'none','acodec':'mp4a.40.2','ext':'m4a'} for lang in langs]}

    def test_all_25_audio_languages_are_listed(self):
        opts = _youtube_lang_options(self.audio(LANGS), PAGE)
        self.assertEqual({o.id for o in opts}, {'ytlang_'+lang for lang in LANGS})

    def test_turkish_after_fourteenth_language_is_not_lost(self):
        opts = _youtube_lang_options(self.audio(LANGS), PAGE)
        self.assertIn('ytlang_tr', [o.id for o in opts])

    def test_selected_audio_language_cannot_fall_back_to_other_language(self):
        opt = _youtube_lang_options(self.audio(['tr']), PAGE)[0]
        self.assertEqual(opt.format_selector, 'bestaudio[language=tr]')

    def test_multiple_encodings_do_not_duplicate_language(self):
        self.assertEqual(len(_youtube_lang_options(self.audio(['tr','tr','en']), PAGE)), 2)

    def test_all_25_manual_subtitle_languages_are_listed(self):
        opts = _youtube_lang_options({'subtitles':{lang:[{'ext':'vtt'}] for lang in LANGS}}, PAGE)
        self.assertEqual({o.sub_lang for o in opts}, set(LANGS))

    def test_late_turkish_subtitle_and_automatic_caption_remain_available(self):
        info = {'subtitles':{lang:[{'ext':'vtt'}] for lang in LANGS},
                'automatic_captions':{'en-orig':[{'ext':'vtt'}], 'tr':[{'ext':'vtt'}]}}
        opts = _youtube_lang_options(info, PAGE)
        self.assertEqual(len(opts), 26)
        self.assertIn('ytsub_man_tr', [o.id for o in opts])
        self.assertIn('ytsub_auto_en-orig', [o.id for o in opts])
        self.assertNotIn('ytsub_auto_tr', [o.id for o in opts])


if __name__ == '__main__':
    unittest.main()
