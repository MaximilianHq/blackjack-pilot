import json

with open(r'C:\Users\maxim\.gemini\antigravity\brain\1369e517-c8c2-4b3c-833e-079cb8923319\.system_generated\logs\transcript.jsonl', encoding='utf-8') as f:
    for idx, line in enumerate(f):
        if idx >= 1700:
            d = json.loads(line)
            src = d.get('source')
            if src == 'USER_EXPLICIT':
                print(f"Step {idx} USER: {d.get('content')}")
            for tc in d.get('tool_calls', []):
                if tc.get('name') in ['replace_file_content', 'write_to_file']:
                    target = tc.get('arguments', {}).get('TargetFile', '')
                    desc = tc.get('arguments', {}).get('Description', '')
                    print(f"Step {idx} TOOL: {tc.get('name')} on {target}: {desc}")
