# minimal IPC client for this fork's API (protobufs in kipy/proto compiled from this tree's api/proto)
import sys,os
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from kipy.client import KiCadClient
from kipy.proto.common.commands import base_commands_pb2 as bc, editor_commands_pb2 as ec
from kipy.proto.common.types import base_types_pb2 as bt, enums_pb2 as en
from kipy.proto.board import board_types_pb2 as bdt, board_commands_pb2 as bdc
MM=1e6
def client(): return KiCadClient(os.environ.get('KPNS_SOCKET','ipc:///tmp/kicad/api.sock'),'nk','',30000)
def board_doc(c):
    r=c.send(ec.GetOpenDocuments(type=bt.DOCTYPE_PCB),ec.GetOpenDocumentsResponse)
    return r.documents[0]
if __name__=='__main__':
    c=client()
    print(c.send(bc.GetVersion(),bc.GetVersionResponse).version)
    d=board_doc(c); print(d)

from google.protobuf import any_pb2
def V(x,y): return bt.Vector2(x_nm=int(round(x*MM)),y_nm=int(round(y*MM)))
def D(v): return bt.Distance(value_nm=int(round(v*MM)))
def tuning_pattern(x0,y0,x1,y1,layer=None,mode='single',tmin=None,topt=None,tmax=None,skew=False,amin=0.1,amax=1.0,spacing=0.3,side=None,single_sided=False,rounded=True):
    tp=bdt.TuningPattern()
    tp.layer=layer if layer is not None else bdt.BL_F_Cu
    tp.origin.CopyFrom(V(x0,y0)); tp.end.CopyFrom(V(x1,y1))
    tp.mode={'single':bdt.TPM_SINGLE,'dp':bdt.TPM_DIFF_PAIR,'skew':bdt.TPM_DIFF_PAIR_SKEW}[mode]
    s=tp.settings; s.initial_side=side if side is not None else bdt.TPMS_DEFAULT
    s.corner_style=bdt.TPCS_ROUNDED if rounded else bdt.TPCS_CHAMFERED; s.corner_radius_percent=80
    s.single_sided=single_sided; s.max_amplitude.CopyFrom(D(amax)); s.min_amplitude.CopyFrom(D(amin)); s.min_spacing.CopyFrom(D(spacing))
    tp.target_mode=bdt.TPTM_LENGTH
    tgt=tp.target_skew if skew else tp.target_length
    if tmin is not None: tgt.min=int(round(tmin*MM))
    if topt is not None: tgt.opt=int(round(topt*MM))
    if tmax is not None: tgt.max=int(round(tmax*MM))
    tp.override_custom_rules=True
    return tp
def create(c,doc,items):
    req=ec.CreateItems(header=bt.ItemHeader(document=doc))
    for it in items:
        a=any_pb2.Any(); a.Pack(it); req.items.append(a)
    return c.send(req,ec.CreateItemsResponse)
def delete(c,doc,ids):
    req=ec.DeleteItems(header=bt.ItemHeader(document=doc))
    for i in ids: req.item_ids.append(i)
    return c.send(req,ec.DeleteItemsResponse)
def try_tp(c,doc,**kw):
    r=create(c,doc,[tuning_pattern(**kw)]); out=bdt.TuningPattern(); r.created_items[0].item.Unpack(out)
    return out
def generators(c,doc):
    r=c.send(ec.GetItems(header=bt.ItemHeader(document=doc),types=[en.KOT_PCB_GENERATOR]),ec.GetItemsResponse)
    out=[]
    for a in r.items:
        tp=bdt.TuningPattern()
        if a.Unpack(tp): out.append(tp)
    return out
def clear_generators(c,doc):
    g=generators(c,doc)
    if g: delete(c,doc,[t.id for t in g])
    return len(g)
