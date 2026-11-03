"""Runtime-check the narrow terminal exception off camera; never disable the guard."""
from pathlib import Path
import subprocess,time,json,os
from desktop_ready import ConsoleGuard,safe_env
out=Path('guard-selftest');out.mkdir(exist_ok=True);guard=ConsoleGuard(out);guard.start()
token=guard.allow_install_terminal('linux-one-line','IDM Linux real scoped terminal selftest')
p=subprocess.Popen(['xterm','-title','IDM Linux real scoped terminal selftest','-e','sleep','4'],env=safe_env(),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
p.wait(10);time.sleep(.6);guard.end_install_terminal(token);result=guard.finish()
assert result['status']=='PASS',json.dumps(result)
assert result['authorized_installation_terminal_events'],'Actual xterm was not recognized by the scoped rule'
print('SCOPED REAL XTERM GUARD RUNTIME PASS',flush=True)
