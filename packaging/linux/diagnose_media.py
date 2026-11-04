#!/usr/bin/env python3
"""Run the real streaming regression with engine logs and bounded ffmpeg stderr evidence."""
import logging
import os
from pathlib import Path
import subprocess
import shutil
import sys
import unittest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
OUT=ROOT/'artifacts/linux-gui';OUT.mkdir(parents=True,exist_ok=True)
from idm_linux.tests.test_suite import TestIdmLinuxSuite
for name in ('stream_engine','hls_streamer','daemon'):
    logger=logging.getLogger(name);logger.addHandler(logging.StreamHandler());logger.setLevel(logging.INFO)
original_which=shutil.which
shutil.which=lambda name,*a,**k: None if name == 'streamlink' else original_which(name,*a,**k)
import idm_linux.distro as distro
def forbidden_install(*args,**kwargs):
    raise AssertionError('A VOD HLS stream must not install streamlink before producing bytes')
distro.ensure_streamlink=forbidden_install
original=subprocess.Popen
handles=[]
def traced_popen(command,*args,**kwargs):
    if command and Path(command[0]).name=='ffmpeg' and kwargs.get('stderr')==subprocess.DEVNULL:
        handle=(OUT/('ffmpeg-stream-stderr-'+str(len(handles))+'.log')).open('wb');handles.append(handle)
        kwargs['stderr']=handle
        print('REAL_FFMPEG_STREAM_COMMAND',command,flush=True)
    return original(command,*args,**kwargs)
subprocess.Popen=traced_popen
try:
    suite=unittest.TestSuite([TestIdmLinuxSuite('test_17_disguised_txt_hls_progressive_realtime_bytes_before_completion')])
    result=unittest.TextTestRunner(verbosity=2).run(suite)
finally:
    subprocess.Popen=original
    for handle in handles:handle.close()
sys.exit(0 if result.wasSuccessful() else 1)
