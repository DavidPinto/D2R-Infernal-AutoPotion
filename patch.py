with open('ui/app.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
for i, line in enumerate(lines):
    if '# Reach Buried Rejuv' in line:
        new_lines.append('        # Predictive Drinking\n')
        new_lines.append('        predictive_frame = ctk.CTkFrame(body, fg_color="transparent")\n')
        new_lines.append('        predictive_frame.pack(fill="x", padx=12, pady=(4, 2))\n')
        new_lines.append('        self._predictive_var = ctk.BooleanVar(value=self.config.behavior.get("predictive_drinking", True))\n')
        new_lines.append('        predictive_cb = ctk.CTkCheckBox(predictive_frame,\n')
        new_lines.append('            text="Predictive Drinking: pre-drink before bars empty (compensates for drain & poison)",\n')
        new_lines.append('            variable=self._predictive_var,\n')
        new_lines.append('            command=self._on_predictive_toggle)\n')
        new_lines.append('        predictive_cb.pack(side="left")\n')
        new_lines.append('        w.hint(predictive_frame, "Predicts how fast you lose Life/Mana and drinks slightly early so the potion has time to work. Also drinks immediately if poisoned. If OFF, drinks exactly at the threshold slider values.").pack(anchor="w", padx=4)\n')
        new_lines.append('\n')
    new_lines.append(line)

with open('ui/app.py', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)
