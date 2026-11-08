"""Actual original native eD2K bridge, own TCP discovery server and own real peer.
No monkeypatches, no engine overrides, no public-network compatibility claim.
ReferenceSeeder is the project's existing real wire-protocol test server, not a mocked client.
"""
import os,time,json,threading,socketserver,socket,struct,hashlib,urllib.parse
from pathlib import Path
O=Path('out/film15-owned-ed2k').resolve();O.mkdir(parents=True,exist_ok=True)
for k,v in [('XDG_CONFIG_HOME','config'),('XDG_DATA_HOME','data'),('XDG_CACHE_HOME','cache')]:os.environ[k]=str(O/v)
from idm_linux.p2p import ed2k_native as E
from idm_linux.tests.test_ed2k_peer_live import ReferenceSeeder
from idm_linux.ed2k_bridge import ed2k_register_native,ed2k_shutdown_all
from idm_linux.config import get_cache_dir
payload=bytes(range(256))*(E.ED2K_PART_SIZE//256)+bytes(range(256))*844
name='İzinli_eD2K_örneği.bin';node=ReferenceSeeder(payload,name);node.start();events=[]
class Discovery(socketserver.BaseRequestHandler):
 def handle(self):
  self.request.settimeout(15)
  try:
   while True:
    packet=E._recv_packet(self.request)
    if packet is None:return
    op,body=packet;events.append({'opcode':op,'payload_bytes':len(body)})
    if op==E.OP_LOGINREQUEST:E._send_packet(self.request,E.OP_IDCHANGE,struct.pack('<I',0x1234))
    elif op in (E.OP_GETSOURCES,E.OP_GETSOURCES_OBFU):
     assert body[:16]==node.file_hash,'Discovery received wrong actual file hash'
     answer=node.file_hash+b'\x01'+socket.inet_aton('127.0.0.1')+struct.pack('<H',node.port)
     E._send_packet(self.request,E.OP_FOUNDSOURCES,answer)
  except (OSError,TimeoutError):return
server=socketserver.ThreadingTCPServer(('127.0.0.1',0),Discovery);server.daemon_threads=True
threading.Thread(target=server.serve_forever,daemon=True).start()
# Supported normal on-disk server-list configuration points only to our real server.
# No replacement fetch function, injected peers, fabricated status, or external hosts.
(get_cache_dir(create=True)/'ed2k_servers.json').write_text(json.dumps({'ts':time.time(),'servers':[['127.0.0.1',server.server_address[1]]]}))
link=f'ed2k://|file|{name}|{len(payload)}|{node.file_hash.hex()}|/'
report={'scope':'Real unmodified native bridge with own real TCP discovery and eD2K peer; not public-network or GUI lesson proof','engine_monkeypatches':False,'injected_client_status':False,'finished_lesson':False,'final_film_export_allowed':False,'filename':name,'source_link_name_representation':'raw Unicode IRI; percent-encoded name edge case is not certified','source_bytes':len(payload),'source_sha256':hashlib.sha256(payload).hexdigest(),'source_ed2k_hash':node.file_hash.hex(),'actual_states':[]}
def save():
 report['actual_discovery_wire_requests']=events;report['actual_peer_served_bytes']=node.served_bytes;report['actual_peer_part_requests']=node.requests
 (O/'actual-owned-ed2k-review.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
try:
 ok,message,result=ed2k_register_native(link,str(O/'actual-downloads'));assert ok,message
 session=result['session'];deadline=time.monotonic()+180
 while time.monotonic()<deadline and not session.complete and not session.error_message:
  report['actual_states'].append(session.query_status());save();time.sleep(.25)
 status=session.query_status();report['actual_states'].append(status)
 assert not session.error_message,session.error_message
 assert session.complete,'Bounded wait expired before actual completion'
 assert session.target_path.name==name,'Actual own Unicode filename must be preserved, not percent-encoded'
 received=session.target_path.read_bytes()
 assert received==payload and session.compute_file_hash()==node.file_hash
 assert status['status']=='complete' and int(status['completedLength'])==len(payload)
 assert E.OP_LOGINREQUEST in [x['opcode'] for x in events] and E.OP_GETSOURCES in [x['opcode'] for x in events]
 assert node.served_bytes>=len(payload) and node.requests>0
 report.update(actual_native_ed2k_bridge_verified=True,actual_output_filename=session.target_path.name,actual_sha256=hashlib.sha256(received).hexdigest(),actual_ed2k_hash=session.compute_file_hash().hex(),multipart_count=session.num_parts,bytes_match=True,original_unicode_filename_preserved=True)
finally:
 ed2k_shutdown_all();node.stop();server.shutdown();server.server_close();save()
