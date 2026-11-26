"""lockcopy.py REF IN OUT : copy the lock flag of every track/via from REF onto IN (matched by net and exact
geometry) and write OUT; copper not in REF ends up unlocked. Use it after pnsfix.py so the temporary locks of
the fork session (lock.py --frozen) do not leak into the deliverable. Needs stock pcbnew."""
import sys

if len(sys.argv) != 4 or sys.argv[1] in ('-h', '--help'):
    print(__doc__)
    sys.exit(0 if len(sys.argv) > 1 and sys.argv[1] in ('-h', '--help') else 2)
import pcbnew as K  # noqa: E402


def key(t):
    if t.GetClass() == 'PCB_VIA':
        return ('v', t.GetNetname(), t.GetPosition().x, t.GetPosition().y)
    s, e = t.GetStart(), t.GetEnd()
    return ('t', t.GetNetname(), t.GetLayer(), tuple(sorted([(s.x, s.y), (e.x, e.y)])))


ref = {key(t): t.IsLocked() for t in K.LoadBoard(sys.argv[1]).GetTracks()}
b = K.LoadBoard(sys.argv[2]); n = 0
for t in b.GetTracks():
    t.SetLocked(ref.get(key(t), False)); n += key(t) in ref
K.SaveBoard(sys.argv[3], b)
print('tracks/vias', len(b.GetTracks()), 'matched REF', n)
