import json

with open(r'C:\Users\maxim\.gemini\antigravity\brain\1369e517-c8c2-4b3c-833e-079cb8923319\.system_generated\logs\transcript.jsonl', encoding='utf-8') as f:
    for idx, line in enumerate(f):
        d = json.loads(line)
        text = str(d.get('content', ''))
        thinking = str(d.get('thinking', ''))
        combined = text + ' ' + thinking
        if 'feed' in combined.lower() and ('overlay' in combined.lower() or 'corner' in combined.lower()):
            if d.get('source') == 'USER_EXPLICIT':
                print(f"Step {idx} USER: {text}")
