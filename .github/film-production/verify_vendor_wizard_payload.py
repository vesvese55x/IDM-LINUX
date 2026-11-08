"""Read-only equality to an original decompressed record in the signed vendor SFX.
Never modify/execute/replace any vendor file or helper. Parent signature is checked by PowerShell.
"""
import sys,hashlib,json
from pathlib import Path
from idm_linux.sfx_unpacker import _pe_overlay_offset,_extract_tonec_records
root,child,out=map(Path,sys.argv[1:4]);data=root.read_bytes();actual=child.read_bytes()
digest=hashlib.sha256(actual).hexdigest()
records=_extract_tonec_records(data,_pe_overlay_offset(data))
indices=[i for i,b in enumerate(records) if b==actual]
report={'original_installer_sha256':hashlib.sha256(data).hexdigest(),'actual_wizard_sha256':digest,'wizard_bytes':len(actual),'exact_original_record_indices':indices,'original_record_count':len(records),'byte_for_byte_match':bool(indices),'vendor_files_modified':False}
out.write_text(json.dumps(report,indent=2))
assert indices,'Actual wizard must be byte-for-byte one original payload record of the signed official installer'
