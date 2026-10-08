import json

with open(r'C:\Users\maxim\.gemini\antigravity\brain\1369e517-c8c2-4b3c-833e-079cb8923319\.system_generated\logs\transcript.jsonl', encoding='utf-8') as f:
    for idx, line in enumerate(f):
        d = json.loads(line)
        content = str(d.get('content', ''))
        if '.bjp-zone-feed' in content and 'bjp-zone-tag' in content and 'border' in content:
            print(f"Step {idx}")
            lines = content.split('\n')
            for i, l in enumerate(lines):
                if '.bjp-zone-box' in l or '.bjp-zone-feed' in l:
                    for sub in lines[max(0, i-2):min(len(lines), i+30)]:
                        print("  ", sub)
                    break
            break

