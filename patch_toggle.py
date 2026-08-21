with open('ui/app.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
for i, line in enumerate(lines):
    if 'def _on_panic_toggle(self):' in line:
        new_lines.append('    def _on_predictive_toggle(self):\n')
        new_lines.append('        self.config.behavior["predictive_drinking"] = self._predictive_var.get()\n')
        new_lines.append('        self.config.save()\n\n')
    new_lines.append(line)

with open('ui/app.py', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)
