with open('d2r/watcher.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
in_effective_percents = False
for line in lines:
    if 'def _effective_percents' in line:
        in_effective_percents = True
    
    if in_effective_percents and 'cfg = self.config' in line:
        new_lines.append(line)
        new_lines.append('        if not cfg.behavior.get("predictive_drinking", True):\n')
        new_lines.append('            return snap.hp_percent, snap.mana_percent\n')
        in_effective_percents = False
    else:
        new_lines.append(line)

with open('d2r/watcher.py', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)
