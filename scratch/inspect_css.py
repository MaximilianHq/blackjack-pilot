import json

with open(r'C:\Users\maxim\.gemini\antigravity\brain\1369e517-c8c2-4b3c-833e-079cb8923319\.system_generated\logs\transcript.jsonl', encoding='utf-8') as f:
    for idx, line in enumerate(f):
        if idx < 1850:
            d = json.loads(line)
            content = str(d.get('content', ''))
            if '.bjp-zone-feed' in content and 'border' in content:
                print(f"Step {idx}")
                for l in content.split('\n'):
                    if any(k in l for k in ['.bjp-zone-feed', '.bjp-zone-box', 'border:']):
                        print("  ", l.encode('ascii', 'replace').decode('ascii'))
