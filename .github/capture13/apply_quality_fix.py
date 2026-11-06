"""Apply narrow, reviewable quality fixes to the checked-out runner source."""
from pathlib import Path
import json
p=Path('src/idm_linux/stream_engine.py')
s=p.read_text()
a='YT_RACE_SECOND_ARGS = "youtube:player_client=default;player_skip=webpage,configs"'
b='YT_RACE_SECOND_ARGS = "youtube:player_client=default"'
assert a in s or b in s,'Upstream changed; inspect before modifying'
s=s.replace(a,b)
a='if is_hls_fmt and v_url.startswith("http"):\n                    # yt-dlp HLS bulduysa doğrudan 16x yerel HLS motoruna bağla!'
b='if is_hls_fmt and v_url.startswith("http") and vf.get("acodec") not in (None, "none"):\n                    # Video-only HLS must use the video+audio mux branch.'
assert a in s or b in s,'Upstream changed HLS branch; inspect before modifying'
s=s.replace(a,b);p.write_text(s)
from idm_linux.stream_engine import StreamEngine
fmts=[{'height':2160,'vcodec':'vp9','acodec':'none','protocol':'m3u8_native','url':'https://example.invalid/video.m3u8','ext':'mp4'},{'vcodec':'none','acodec':'aac','protocol':'https','url':'https://example.invalid/audio.m4a','ext':'m4a','abr':128}]
opt=next(o for o in StreamEngine._summarize_ytdlp_formats(None,fmts,'https://example.invalid/test') if o.height==2160)
assert not opt.is_hls and opt.mux_video_url and opt.mux_audio_url
print('QUALITY_FIX_REGRESSION_PASS')
