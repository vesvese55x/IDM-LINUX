"""Read actual Windows accessibility checkbox state. Never alter product UI/state."""
import sys,json
from pywinauto.uia_element_info import UIAElementInfo
from pywinauto.controls.uiawrapper import UIAWrapper
w=UIAWrapper(UIAElementInfo(int(sys.argv[1])))
try:
 value=int(w.iface_toggle.CurrentToggleState);assert value in (0,1)
 method='Windows UI Automation TogglePattern';checked=value==1
except Exception:
 props=w.legacy_properties();value=int(props['State']);checked=bool(value&16)
 method='Windows MSAA checked state'
print(json.dumps({'name':w.element_info.name,'checked':checked,'raw_state':value,'read_method':method,'product_ui_modified':False},ensure_ascii=False))
