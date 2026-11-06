# Restore the 10 tested_by edges that merge-batch-graphs.py dropped as "prod<->prod pair".
# Both endpoints exist in the graph and are test harnesses (scripts/acceptance.py,
# scripts/smoke_e2e.py) -> the filename heuristic false-positived. Edges are restored
# byte-for-byte as the batches emitted them.
import json, collections

ROOT = r'C:\Users\PC\Documents\GitHub\ocr-app'
GP = ROOT + r'\.ua\intermediate\assembled-graph.json'
BK = ROOT + r'\.ua\tmp\peer-backup-1793967395'

g = json.load(open(GP, encoding='utf-8'))
byid = {n['id'] for n in g['nodes']}
have = {(e['source'], e['target'], e['type']) for e in g['edges']}

restored = []
for nm in ('batch-2-part-1.json', 'batch-4.json'):
    d = json.load(open(BK + '\\' + nm, encoding='utf-8'))
    for e in d.get('edges', []):
        if e.get('type') != 'tested_by':
            continue
        key = (e['source'], e['target'], e['type'])
        if key in have or e['source'] not in byid or e['target'] not in byid:
            continue
        # keep the same key order as existing edges
        edge = {'source': e['source'], 'target': e['target'], 'type': e['type'],
                'direction': e.get('direction', 'forward'), 'weight': e.get('weight', 0.5)}
        g['edges'].append(edge)
        have.add(key)
        restored.append(key)

# keep the file's existing CRLF line endings and lack of trailing newline
with open(GP, 'w', encoding='utf-8', newline='\r\n') as f:
    json.dump(g, f, ensure_ascii=False, indent=2)

# re-validate
g2 = json.load(open(GP, encoding='utf-8'))
ids = {n['id'] for n in g2['nodes']}
dang = [e for e in g2['edges'] if e['source'] not in ids or e['target'] not in ids]
dup = [k for k, v in collections.Counter((e['source'], e['target'], e['type']) for e in g2['edges']).items() if v > 1]
print('restored', len(restored))
for r in restored: print('  ', r)
print('nodes', len(g2['nodes']), 'edges', len(g2['edges']))
print('dangling', len(dang), 'dup', dup)
print('tested_by now', sum(1 for e in g2['edges'] if e['type'] == 'tested_by'))
print('type counts', dict(collections.Counter(e['type'] for e in g2['edges'])))
