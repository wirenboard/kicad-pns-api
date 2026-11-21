# client helpers for the push & shove router API of this fork (RouteTrack, DragTrack, CleanupTracks, RunDrc)
import sys,os
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from nk_base import *
from kipy.proto.board import board_commands_pb2 as pc
MODES={'shove':pc.RTM_SHOVE,'walkaround':pc.RTM_WALKAROUND,'mark':pc.RTM_MARK_OBSTACLES}
CORNERS={None:0,'mitered45':pc.RCM_MITERED_45,'rounded45':pc.RCM_ROUNDED_45,'mitered90':pc.RCM_MITERED_90,'rounded90':pc.RCM_ROUNDED_90}
def route_track(c,doc,start,points,layer=bdt.BL_F_Cu,mode='shove',width=None,finish=False,free_angle=False,
                diff_pair=False,gap=None,corner=None,point_layers=None,via_diameter=None,via_drill=None):
    """points: list of (x,y) mm; point_layers: optional list of BoardLayer per point (layer change = via)"""
    r=pc.RouteTrack(board=doc,layer=layer,mode=MODES[mode],finish_at_last_point=finish,free_angle=free_angle,
                    diff_pair=diff_pair,corner_mode=CORNERS[corner])
    r.start.CopyFrom(V(*start))
    for p in points: r.points.append(V(*p))
    if point_layers:
        for l in point_layers: r.point_layers.append(l)
    if width: r.width.CopyFrom(D(width))
    if gap: r.diff_pair_gap.CopyFrom(D(gap))
    if via_diameter: r.via_diameter.CopyFrom(D(via_diameter))
    if via_drill: r.via_drill.CopyFrom(D(via_drill))
    return c.send(r,pc.RouteTrackResponse)
def drag_track(c,doc,grab,target,layer=bdt.BL_F_Cu,mode='shove',free_angle=False):
    r=pc.DragTrack(board=doc,layer=layer,mode=MODES[mode],free_angle=free_angle)
    r.grab.CopyFrom(V(*grab)); r.target.CopyFrom(V(*target))
    return c.send(r,pc.DragTrackResponse)
def client_here():
    """client for $KPNS_SOCKET (default: instance 1 of host/hoststart_n.sh)"""
    return KiCadClient(os.environ.get('KPNS_SOCKET',socket_of(1)),'pns','',60000)
def tracks_of(c,doc,net):
    r=c.send(ec.GetItems(header=bt.ItemHeader(document=doc),types=[en.KOT_PCB_TRACE,en.KOT_PCB_ARC]),ec.GetItemsResponse)
    out=[]
    for a in r.items:
        t=bdt.Track()
        if a.Unpack(t) and t.net.name==net: out.append(((t.start.x_nm/1e6,t.start.y_nm/1e6),(t.end.x_nm/1e6,t.end.y_nm/1e6),t.layer))
    return out

def cleanup_tracks(c,doc,nets=(),merge=True,dangling=False,in_pads=False,shorting=False,redundant_vias=False,dangling_vias=False,dry_run=False):
    r=pc.CleanupTracks(board=doc,merge_segments=merge,delete_dangling_tracks=dangling,delete_tracks_in_pads=in_pads,
                       delete_shorting_tracks=shorting,delete_redundant_vias=redundant_vias,delete_dangling_vias=dangling_vias,dry_run=dry_run)
    for n in nets: r.nets.append(n)
    return list(c.send(r,pc.CleanupTracksResponse).changes)
def run_drc(c,doc,nets=(),refill=False,all_track_errors=False):
    r=pc.RunDrc(board=doc,refill_zones=refill,report_all_track_errors=all_track_errors)
    for n in nets: r.nets.append(n)
    return list(c.send(r,pc.RunDrcResponse).violations)

def socket_of(n):
    """API socket of instance n started by host/hoststart_n.sh ($KPNS_SOCK_PREFIX, default /tmp/kpns)"""
    return f"ipc://{os.environ.get('KPNS_SOCK_PREFIX','/tmp/kpns')}{n}/kicad/api.sock"
def client_inst(n,timeout_ms=60000):
    """client for instance n started by host/hoststart_n.sh N (own socket)"""
    return KiCadClient(socket_of(n),f'pns{n}','',timeout_ms)

# ---- snapshot / rollback of all copper (tracks, arcs, vias): undo a failed route attempt.
# Failed shove attempts can leave neighbours moved; restore everything that differs.
from google.protobuf import any_pb2 as _any
_KINDS=((en.KOT_PCB_TRACE,bdt.Track),(en.KOT_PCB_ARC,bdt.Arc),(en.KOT_PCB_VIA,bdt.Via))
def copper_items(c,doc):
    """{id: Track|Arc|Via} of the whole board"""
    out={}
    for kind,cls in _KINDS:
        r=c.send(ec.GetItems(header=bt.ItemHeader(document=doc),types=[kind]),ec.GetItemsResponse)
        for a in r.items:
            o=cls()
            if a.Unpack(o): out[o.id.value]=o
    return out
def snapshot(c,doc):
    return copper_items(c,doc)
def rollback(c,doc,before):
    """make the board's copper equal to snapshot `before`: delete items that are new or changed,
    re-create the removed/changed originals (they get new ids). Returns (deleted, recreated)."""
    now=copper_items(c,doc)
    stale=[k for k,o in now.items() if k not in before or o.SerializeToString(deterministic=True)!=before[k].SerializeToString(deterministic=True)]
    lost=[before[k] for k in before if k not in now or k in stale]
    if stale: delete(c,doc,[now[k].id for k in stale])
    if lost:
        req=ec.CreateItems(header=bt.ItemHeader(document=doc))
        for o in lost:
            n=type(o)(); n.CopyFrom(o); n.ClearField('id')
            a=_any.Any(); a.Pack(n); req.items.append(a)
        c.send(req,ec.CreateItemsResponse)
    return len(stale),len(lost)
