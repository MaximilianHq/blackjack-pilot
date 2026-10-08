import json

with open(r'C:\Users\maxim\.gemini\antigravity\brain\1369e517-c8c2-4b3c-833e-079cb8923319\.system_generated\logs\transcript.jsonl', encoding='utf-8') as f:
    for idx, line in enumerate(f):
        if idx in [1480, 1588, 1750, 1800]:
            d = json.loads(line)
            content = str(d.get('content', ''))
            print(f"=== STEP {idx} ===")
            for l in content.split('\n'):
                if any(k in l for k in ['feedBoxEl', 'bjp-zone-feed', 'makeCornerBox', 'applyOverlayPositions', 'feedRect']):
                    print(l.encode('ascii', 'replace').decode('ascii'))
