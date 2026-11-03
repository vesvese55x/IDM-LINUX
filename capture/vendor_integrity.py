"""Verify official vendor binary, retaining honest manifest mismatch evidence."""
import os,json,subprocess,re,hashlib

def verify(path,expected):
 actual=hashlib.sha256(path.read_bytes()).hexdigest()
 evidence={'actual_sha256':actual,'expected_sha256':expected,'match':actual==expected}
 if evidence['match']:
  evidence['acceptance_basis']='Exact Microsoft winget manifest SHA256';return evidence
 # Vendor has replaced the bytes at its official fixed-version URL. A matching
 # second download alone is NOT enough. Require Windows trusted Authenticode
 # and the named original publisher, or stop before any wizard interaction.
 env=dict(os.environ);env['FILM_VENDOR_FILE']=str(path)
 script="""[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false); $s=Get-AuthenticodeSignature -LiteralPath $env:FILM_VENDOR_FILE; $v=[Diagnostics.FileVersionInfo]::GetVersionInfo($env:FILM_VENDOR_FILE); @{status=[string]$s.Status;message=$s.StatusMessage;subject=$s.SignerCertificate.Subject;thumbprint=$s.SignerCertificate.Thumbprint;timestamp_subject=$s.TimeStamperCertificate.Subject;file_version=$v.FileVersion;product_name=$v.ProductName;company_name=$v.CompanyName} | ConvertTo-Json -Compress"""
 r=subprocess.run(['powershell.exe','-NoLogo','-NoProfile','-NonInteractive','-Command',script],env=env,creationflags=subprocess.CREATE_NO_WINDOW,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=50)
 try:sig=json.loads(r.stdout.strip().lstrip('\ufeff'))
 except Exception:sig={'status':'UNVERIFIED','error':'Signature verifier did not return valid JSON','returncode':r.returncode}
 evidence['authenticode']=sig
 subject=sig.get('subject') or ''
 publisher=bool(re.search(r'(?:^|,\s*)CN\s*=\s*"?(?:Tonec Inc\.?|Tonec FZE)"?(?:,|$)',subject,re.I))
 evidence['trusted_named_publisher']=publisher
 evidence['accepted']=r.returncode==0 and sig.get('status')=='Valid' and publisher
 evidence['acceptance_basis']='Trusted Windows Authenticode certificate for Tonec; upstream winget SHA mismatch retained' if evidence['accepted'] else 'REJECT — manifest mismatch and no verified trusted Tonec signature'
 return evidence
