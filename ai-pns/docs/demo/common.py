"""common.py : shared setup of the demo scripts (python with protobuf 5.29 + pynng, i.e. $KPNS_PY).
The instance number comes from $DEMO_N (default 1), as started by host/hoststart_n.sh."""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'pyapi'))
import pns                      # noqa: E402
from nk_base import bdt         # noqa: E402,F401
N = int(os.environ.get('DEMO_N', '1'))


def connect():
    c = pns.client_inst(N, 600000)
    return c, pns.board_doc(c)
