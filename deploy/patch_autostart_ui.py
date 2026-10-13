#!/usr/bin/env python3
"""Patch AI Runtime Manager's index.html to add autostart toggle for systemd services.

Adds:
- CSS toggle switch component
- autostartMap state + fetch on service load
- Toggle switch in each systemd service card (below start/stop buttons)
- toggleAutostart() API call function

Prerequisites:
- patch_autostart.py must have been run first (adds backend API endpoints)
- sudoers must grant systemctl enable/disable/is-enabled for target services
"""

import re

TARGET = "/home/manfred/ai-local/services/manager/index.html"

with open(TARGET, "r", encoding="utf-8") as f:
    html = f.read()

# 1. Add toggle switch CSS before </style>
toggle_css = """\
.toggle{position:relative;display:inline-block;width:36px;height:20px;flex-shrink:0}
.toggle input{opacity:0;width:0;height:0;position:absolute}
.toggle .slider{position:absolute;inset:0;background:var(--border);border-radius:20px;transition:background .2s;cursor:pointer}
.toggle .slider::before{content:'';position:absolute;width:14px;height:14px;left:3px;bottom:3px;background:var(--text2);border-radius:50%;transition:transform .2s,background .2s}
.toggle input:checked+.slider{background:var(--accent)}
.toggle input:checked+.slider::before{transform:translateX(16px);background:white}
"""

if ".toggle" not in html:
    html = html.replace(
        "</style>",
        toggle_css + "</style>",
    )
    print("1. Toggle CSS added")
else:
    print("1. Toggle CSS already present, skipping")

# 2. Add autostartMap variable
if "autostartMap" not in html:
    html = html.replace(
        "let autotuneTimer = null;",
        "let autotuneTimer = null;\nlet autostartMap = {};",
    )
    print("2. autostartMap variable added")
else:
    print("2. autostartMap already present, skipping")

# 3. Modify loadServices() to fetch autostart status for systemd services
old_load = """\
async function loadServices(){
  try{
    const data=await api('/api/services');
    services=data.services;
    renderServices();renderLocalModels();renderMonitorServices();updateLogSelect();updateChatSelect();updateOmniSelect();
  }catch(e){console.error('loadServices:',e);}
}"""

new_load = """\
async function loadServices(){
  try{
    const data=await api('/api/services');
    services=data.services;
    renderServices();renderLocalModels();renderMonitorServices();updateLogSelect();updateChatSelect();updateOmniSelect();
    // Fetch autostart status for systemd services
    const systemdSvcs=services.filter(s=>s.type==='systemd');
    await Promise.all(systemdSvcs.map(async s=>{
      try{const r=await api(`/api/services/${s.id}/autostart`);autostartMap[s.id]=r.autostart;}
      catch(e){autostartMap[s.id]=false;}
    }));
    renderServices();
  }catch(e){console.error('loadServices:',e);}
}"""

if old_load in html and "autostartMap[s.id]" not in html:
    html = html.replace(old_load, new_load)
    print("3. loadServices() patched with autostart fetch")
else:
    print("3. loadServices() already patched or pattern not found, skipping")

# 4. Modify renderServices() to show autostart toggle
old_render_tile_end = """\
      </div>
    </div>`;
  }).join('');
}"""

# Find the renderServices function and replace the service tile template
# We need to add the autostart toggle after the start/stop buttons div
old_tile_buttons = """\
      <div style="margin-top:10px;display:flex;gap:6px;justify-content:center">
        ${s.status==='running'
          ?`<button class="btn btn-sm btn-danger" onclick="event.stopPropagation();stopSvc('${s.id}')">停止</button><button class="btn btn-sm btn-ghost" onclick="event.stopPropagation();restartSvc('${s.id}')">重启</button>`
          :s.status==='error'
          ?`<button class="btn btn-sm btn-danger" onclick="event.stopPropagation();stopSvc('${s.id}')">强制停止</button><button class="btn btn-sm btn-success" onclick="event.stopPropagation();startSvc('${s.id}')">重启</button>`
          :`<button class="btn btn-sm btn-success" onclick="event.stopPropagation();startSvc('${s.id}')">启动</button>`}
      </div>
    </div>`"""

new_tile_buttons = """\
      <div style="margin-top:10px;display:flex;gap:6px;justify-content:center">
        ${s.status==='running'
          ?`<button class="btn btn-sm btn-danger" onclick="event.stopPropagation();stopSvc('${s.id}')">停止</button><button class="btn btn-sm btn-ghost" onclick="event.stopPropagation();restartSvc('${s.id}')">重启</button>`
          :s.status==='error'
          ?`<button class="btn btn-sm btn-danger" onclick="event.stopPropagation();stopSvc('${s.id}')">强制停止</button><button class="btn btn-sm btn-success" onclick="event.stopPropagation();startSvc('${s.id}')">重启</button>`
          :`<button class="btn btn-sm btn-success" onclick="event.stopPropagation();startSvc('${s.id}')">启动</button>`}
      </div>
      ${isSystemd
        ?`<div style="margin-top:8px;display:flex;align-items:center;justify-content:center;gap:6px" onclick="event.stopPropagation()"><label class="toggle"><input type="checkbox" ${autostartOn?'checked':''} onchange="toggleAutostart('${s.id}',this.checked)"><span class="slider"></span></label><span style="font-size:11px;color:var(--text2)">开机自启</span></div>`
        :''}
    </div>`"""

if "toggleAutostart" not in html and old_tile_buttons in html:
    html = html.replace(old_tile_buttons, new_tile_buttons)
    print("4. Service tile template patched with autostart toggle")
else:
    print("4. Service tile already has toggle or pattern not found, skipping")

# Also add the isSystemd and autostartOn variables before the return statement
# Find the "const sel=" line and add the new vars after model
old_vars = "    const sel=selectedService===s.id?'selected':'';"
new_vars = "    const isSystemd=s.type==='systemd';\n    const autostartOn=!!autostartMap[s.id];\n    const sel=selectedService===s.id?'selected':'';"

if "isSystemd" not in html and old_vars in html:
    html = html.replace(old_vars, new_vars)
    print("5. isSystemd/autostartOn variables added to renderServices")
else:
    print("5. Variables already present or pattern not found, skipping")

# 5. Add toggleAutostart function after stopSvc
old_stop = "async function stopSvc(id){try{await api(`/api/services/${id}/stop`,'POST');toast(id+' 已停止');}catch(e){toast(e.message,'error');}}"
new_stop = """\
async function stopSvc(id){try{await api(`/api/services/${id}/stop`,'POST');toast(id+' 已停止');}catch(e){toast(e.message,'error');}}
async function toggleAutostart(id,enabled){
  try{await api(`/api/services/${id}/autostart`,'POST',{enabled});autostartMap[id]=enabled;toast(id+(enabled?' 开机自启已启用':' 开机自启已关闭'));}
  catch(e){toast(e.message,'error');renderServices();}
}"""

if "toggleAutostart" not in html and old_stop in html:
    html = html.replace(old_stop, new_stop)
    print("6. toggleAutostart function added")
else:
    print("6. toggleAutostart already present or stopSvc not found, skipping")

with open(TARGET, "w", encoding="utf-8") as f:
    f.write(html)

print("PATCHED OK")
