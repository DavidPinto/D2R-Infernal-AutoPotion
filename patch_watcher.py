with open('d2r/watcher.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
for line in lines:
    if 'cfg = self.config' in line:
        new_lines.append(line)
        new_lines.append('        if not cfg.behavior.get("predictive_drinking", True):\n')
        new_lines.append('            return snap.hp_percent, snap.mana_percent\n')
    else:
        new_lines.append(line)

with open('d2r/watcher.py', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)
