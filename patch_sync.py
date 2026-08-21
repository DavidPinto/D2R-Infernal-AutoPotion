with open('ui/app.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
for i, line in enumerate(lines):
    new_lines.append(line)
    if 'self._panic_var.set(self.config.reach_buried_rejuv)' in line:
        new_lines.append('        self._predictive_var.set(self.config.behavior.get("predictive_drinking", True))\n')
    elif 'self.config.behavior["reach_buried_rejuv"] = DEFAULTS["behavior"]["reach_buried_rejuv"]' in line:
        new_lines.append('        self.config.behavior["predictive_drinking"] = DEFAULTS["behavior"]["predictive_drinking"]\n')

with open('ui/app.py', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)
