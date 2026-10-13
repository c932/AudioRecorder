#!/usr/bin/env python3
"""Patch AI Runtime Manager to support autostart for ALL service types.

Changes:
1. config.py — add update_service_autostart() and get_service_autostart()
2. service_registry.py — rewrite autostart methods to work for all service types,
   add autostart_all() for manager boot-time auto-start
3. main.py — update autostart API, call autostart_all() in lifespan
4. index.html — show autostart toggle for ALL services (not just systemd)
"""

import re

BASE = "/home/manfred/ai-local/services/manager"

# ═══════════════════════════════════════════════════════════════════════
# 1. config.py — add autostart persistence functions
# ═══════════════════════════════════════════════════════════════════════

with open(f"{BASE}/config.py", "r", encoding="utf-8") as f:
    config_py = f.read()

if "update_service_autostart" not in config_py:
    config_py += '''

def update_service_autostart(service_id: str, autostart: bool) -> bool:
    """Set the autostart flag for a service. Returns True if found and updated."""
    with _lock:
        raw = _load_raw()
        if service_id not in raw.get("services", {}):
            return False
        raw["services"][service_id]["autostart"] = autostart
        _save_raw(raw)
    return True


def get_service_autostart(service_id: str) -> bool:
    """Read the autostart flag for a service from config. Defaults to False."""
    with _lock:
        raw = _load_raw()
        svc = raw.get("services", {}).get(service_id, {})
        return bool(svc.get("autostart", False))
'''
    with open(f"{BASE}/config.py", "w", encoding="utf-8") as f:
        f.write(config_py)
    print("1. config.py patched — added autostart persistence")
else:
    print("1. config.py already patched, skipping")

# ═══════════════════════════════════════════════════════════════════════
# 2. service_registry.py — rewrite autostart for all service types
# ═══════════════════════════════════════════════════════════════════════

with open(f"{BASE}/service_registry.py", "r", encoding="utf-8") as f:
    sr = f.read()

# 2a. Replace the systemd-only autostart section with universal version
old_autostart_section = '''    # ------------------------------------------------------------------ #
    #  Autostart (systemctl enable/disable)
    # ------------------------------------------------------------------ #

    async def set_autostart(self, service_id: str, enabled: bool) -> ServiceState:
        """Enable or disable systemd autostart for a service."""
        state = self._states.get(service_id)
        if not state or not state.config:
            raise ValueError(f"Service '{service_id}' not found")
        if state.config.type != ServiceType.SYSTEMD:
            raise ValueError(f"Service '{service_id}' is not a systemd service")
        unit = state.config.systemd_unit or state.config.params.get("systemd_unit", "")
        if not unit:
            raise ValueError(f"Service '{service_id}' has no systemd_unit")

        action = "enable" if enabled else "disable"
        result = subprocess.run(
            ["sudo", "systemctl", action, unit],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            raise RuntimeError(f"systemctl {action} {unit} failed: {result.stderr}")

        # Update config to persist the autostart preference
        state.config.params["autostart"] = enabled
        logger.info("Autostart %s for %s (%s)", "enabled" if enabled else "disabled", service_id, unit)
        return state

    def get_autostart(self, service_id: str) -> bool:
        """Check if a service has autostart enabled via systemd."""
        state = self._states.get(service_id)
        if not state or not state.config:
            return False
        if state.config.type != ServiceType.SYSTEMD:
            return False
        unit = state.config.systemd_unit or state.config.params.get("systemd_unit", "")
        if not unit:
            return False
        try:
            result = subprocess.run(
                ["systemctl", "is-enabled", unit],
                capture_output=True, text=True, timeout=5,
            )
            return result.stdout.strip() == "enabled"
        except Exception:
            return False'''

new_autostart_section = '''    # ------------------------------------------------------------------ #
    #  Autostart — AI Runtime auto-starts services on boot
    # ------------------------------------------------------------------ #

    async def set_autostart(self, service_id: str, enabled: bool) -> ServiceState:
        """Enable or disable autostart for a service (any type).

        For systemd services, also runs systemctl enable/disable so the OS-level
        autostart stays in sync with the AI Runtime autostart flag.
        """
        state = self._states.get(service_id)
        if not state or not state.config:
            raise ValueError(f"Service '{service_id}' not found")

        # Persist to services.json
        cfg.update_service_autostart(service_id, enabled)
        # Also update in-memory config
        state.config.autostart = enabled

        # For systemd services, also sync systemctl enable/disable
        if state.config.type == ServiceType.SYSTEMD:
            unit = state.config.systemd_unit or state.config.params.get("systemd_unit", "")
            if unit:
                action = "enable" if enabled else "disable"
                try:
                    result = subprocess.run(
                        ["sudo", "systemctl", action, unit],
                        capture_output=True, text=True, timeout=15,
                    )
                    if result.returncode != 0:
                        logger.warning("systemctl %s %s failed: %s", action, unit, result.stderr)
                    else:
                        logger.info("systemctl %s %s OK", action, unit)
                except Exception as e:
                    logger.warning("systemctl %s %s error: %s", action, unit, e)

        logger.info("Autostart %s for %s", "enabled" if enabled else "disabled", service_id)
        return state

    def get_autostart(self, service_id: str) -> bool:
        """Check if a service has autostart enabled.

        For systemd services, checks systemctl is-enabled as the source of truth
        (since that's what actually controls OS-level boot autostart).
        Falls back to services.json for non-systemd services.
        """
        state = self._states.get(service_id)
        if state and state.config and state.config.type == ServiceType.SYSTEMD:
            unit = state.config.systemd_unit or state.config.params.get("systemd_unit", "")
            if unit:
                try:
                    result = subprocess.run(
                        ["systemctl", "is-enabled", unit],
                        capture_output=True, text=True, timeout=5,
                    )
                    is_enabled = result.stdout.strip() == "enabled"
                    # Sync services.json with the actual state
                    cfg.update_service_autostart(service_id, is_enabled)
                    return is_enabled
                except Exception:
                    pass
        return cfg.get_service_autostart(service_id)

    async def autostart_all(self) -> None:
        """Auto-start all services that have autostart enabled.

        Called once during Manager startup. Services are started sequentially
        to avoid overwhelming GPU memory.
        """
        for sid, state in list(self._states.items()):
            if cfg.get_service_autostart(sid):
                logger.info("Autostart: starting %s", sid)
                try:
                    await self.start_service(sid)
                    logger.info("Autostart: %s started successfully", sid)
                except Exception as e:
                    logger.warning("Autostart: failed to start %s: %s", sid, e)
                # Delay between starts to let GPU settle
                await asyncio.sleep(3)'''

if old_autostart_section in sr:
    sr = sr.replace(old_autostart_section, new_autostart_section)
    print("2a. service_registry.py — autostart section rewritten for all types")
elif "autostart_all" in sr:
    print("2a. service_registry.py — already patched with universal autostart")
else:
    # Fallback: find and replace just the key methods
    print("2a. service_registry.py — exact match not found, trying regex fallback")
    # Replace the old set_autostart method
    sr = re.sub(
        r'    async def set_autostart\(self.*?\n(?=    (?:async )?def |    # ----)',
        new_autostart_section + '\n',
        sr,
        flags=re.DOTALL,
    )
    print("2a. service_registry.py — autostart patched via regex")

# 2b. Add 'autostart' field to the ServiceConfig model if not present
# (We handle this in models.py below)

with open(f"{BASE}/service_registry.py", "w", encoding="utf-8") as f:
    f.write(sr)
print("2b. service_registry.py saved")

# ═══════════════════════════════════════════════════════════════════════
# 3. models.py — add autostart field to ServiceConfig
# ═══════════════════════════════════════════════════════════════════════

with open(f"{BASE}/models.py", "r", encoding="utf-8") as f:
    models = f.read()

if "autostart" not in models:
    # Add autostart field to ServiceConfig
    old_sc = '    enabled: bool = True'
    new_sc = '    enabled: bool = True\n    autostart: bool = False'
    models = models.replace(old_sc, new_sc)
    with open(f"{BASE}/models.py", "w", encoding="utf-8") as f:
        f.write(models)
    print("3. models.py — added autostart field to ServiceConfig")
else:
    print("3. models.py — autostart field already present")

# ═══════════════════════════════════════════════════════════════════════
# 4. main.py — update autostart API + call autostart_all in lifespan
# ═══════════════════════════════════════════════════════════════════════

with open(f"{BASE}/main.py", "r", encoding="utf-8") as f:
    main = f.read()

# 4a. Update lifespan to call autostart_all
old_lifespan = '''    await registry.start_patrol()
    # Start API Gateway'''
new_lifespan = '''    await registry.start_patrol()
    # Auto-start services that have autostart enabled
    await registry.autostart_all()
    # Start API Gateway'''

if "autostart_all" not in main:
    main = main.replace(old_lifespan, new_lifespan)
    print("4a. main.py — added autostart_all() call in lifespan")
else:
    print("4a. main.py — autostart_all already in lifespan")

# 4b. Update autostart API docstrings (remove systemd-only wording)
main = main.replace(
    '"""Enable or disable systemd autostart for a service."""',
    '"""Enable or disable autostart for a service (auto-start on Manager boot)."""',
)
main = main.replace(
    '"""Check if a service has autostart enabled."""',
    '"""Check if a service has autostart enabled (auto-start on Manager boot)."""',
)
print("4b. main.py — updated autostart API docstrings")

# 4c. Remove ValueError restriction in set_autostart endpoint (no longer systemd-only)
# The backend will handle it, but let's also make sure the error handling is right
old_set_endpoint = '''@app.post("/api/services/{service_id}/autostart")
async def set_autostart(service_id: str, req: AutostartRequest, _: dict = Depends(get_current_user_or_localhost)):
    """Enable or disable autostart for a service (auto-start on Manager boot)."""
    try:
        state = await registry.set_autostart(service_id, req.enabled)
        return {"success": True, "service_id": service_id, "autostart": req.enabled}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(500, str(e))'''

new_set_endpoint = '''@app.post("/api/services/{service_id}/autostart")
async def set_autostart(service_id: str, req: AutostartRequest, _: dict = Depends(get_current_user_or_localhost)):
    """Enable or disable autostart for a service (auto-start on Manager boot)."""
    try:
        state = await registry.set_autostart(service_id, req.enabled)
        return {"success": True, "service_id": service_id, "autostart": req.enabled}
    except ValueError as e:
        raise HTTPException(400, str(e))'''

main = main.replace(old_set_endpoint, new_set_endpoint)
print("4c. main.py — simplified set_autostart endpoint (removed RuntimeError)")

with open(f"{BASE}/main.py", "w", encoding="utf-8") as f:
    f.write(main)
print("4d. main.py saved")

# ═══════════════════════════════════════════════════════════════════════
# 5. index.html — show autostart toggle for ALL services
# ═══════════════════════════════════════════════════════════════════════

with open(f"{BASE}/index.html", "r", encoding="utf-8") as f:
    html = f.read()

# 5a. Remove the isSystemd restriction from the autostart toggle HTML
# Change: const isSystemd=s.type==='systemd'; → (remove, or keep but don't gate on it)
# Change: ${isSystemd ?`...` :''} → always show the toggle
if "isSystemd" in html and "autostartHtml" in html:
    # Remove the isSystemd variable (no longer needed)
    html = html.replace("    const isSystemd=s.type==='systemd';\n", "")
    # Remove the isSystemd ternary — always show toggle
    html = html.replace(
        "${isSystemd\n        ?`<div style=\"margin-top:8px;display:flex;align-items:center;justify-content:center;gap:6px\" onclick=\"event.stopPropagation()\"><label class=\"toggle\"><input type=\"checkbox\" ${autostartOn?'checked':''} onchange=\"toggleAutostart('${s.id}',this.checked)\"><span class=\"slider\"></span></label><span style=\"font-size:11px;color:var(--text2)\">开机自启</span></div>\n        :''}",
        "<div style=\"margin-top:8px;display:flex;align-items:center;justify-content:center;gap:6px\" onclick=\"event.stopPropagation()\"><label class=\"toggle\"><input type=\"checkbox\" ${autostartOn?'checked':''} onchange=\"toggleAutostart('${s.id}',this.checked)\"><span class=\"slider\"></span></label><span style=\"font-size:11px;color:var(--text2)\">开机自启</span></div>",
    )
    print("5a. index.html — removed isSystemd restriction, toggle shown for all services")
elif "开机自启" in html:
    # May already be partially patched, check the current state
    # If the ternary is on one line:
    html = re.sub(
        r'\$\{isSystemd\s*\?`([^`]*)`\s*:\s*\'\'\}',
        r'$1',
        html,
    )
    print("5a. index.html — removed isSystemd restriction via regex")
else:
    # Need to add the full autostart UI (first-time patch)
    print("5a. index.html — need to add autostart UI from scratch")

    # Add toggle CSS
    toggle_css = ".toggle{position:relative;display:inline-block;width:36px;height:20px;flex-shrink:0}.toggle input{opacity:0;width:0;height:0;position:absolute}.toggle .slider{position:absolute;inset:0;background:var(--border);border-radius:20px;transition:background .2s;cursor:pointer}.toggle .slider::before{content:'';position:absolute;width:14px;height:14px;left:3px;bottom:3px;background:var(--text2);border-radius:50%;transition:transform .2s,background .2s}.toggle input:checked+.slider{background:var(--accent)}.toggle input:checked+.slider::before{transform:translateX(16px);background:white}"
    html = html.replace("</style>", toggle_css + "\n</style>")

    # Add autostartMap variable
    html = html.replace(
        "let autotuneTimer = null;",
        "let autotuneTimer = null;\nlet autostartMap = {};",
    )

    # Add autostart fetch in loadServices
    html = html.replace(
        "    renderServices();renderLocalModels();renderMonitorServices();updateLogSelect();updateChatSelect();updateOmniSelect();\n  }catch(e){console.error('loadServices:',e);}",
        "    renderServices();renderLocalModels();renderMonitorServices();updateLogSelect();updateChatSelect();updateOmniSelect();\n    // Fetch autostart status for all services\n    await Promise.all(services.map(async s=>{\n      try{const r=await api(`/api/services/${s.id}/autostart`);autostartMap[s.id]=r.autostart;}\n      catch(e){autostartMap[s.id]=false;}\n    }));\n    renderServices();\n  }catch(e){console.error('loadServices:',e);}",
    )

    # Add autostart toggle to service cards (after the buttons div, before closing div)
    html = html.replace(
        "      </div>\n    </div>`;\n  }).join('');\n}",
        "      </div>\n      <div style=\"margin-top:8px;display:flex;align-items:center;justify-content:center;gap:6px\" onclick=\"event.stopPropagation()\"><label class=\"toggle\"><input type=\"checkbox\" ${autostartOn?'checked':''} onchange=\"toggleAutostart('${s.id}',this.checked)\"><span class=\"slider\"></span></label><span style=\"font-size:11px;color:var(--text2)\">开机自启</span></div>\n    </div>`;\n  }).join('');\n}",
    )

    # Add autostartOn variable
    html = html.replace(
        "    const sel=selectedService===s.id?'selected':'';",
        "    const autostartOn=!!autostartMap[s.id];\n    const sel=selectedService===s.id?'selected':'';",
    )

    # Add toggleAutostart function
    html = html.replace(
        "async function stopSvc(id){try{await api(`/api/services/${id}/stop`,'POST');toast(id+' 已停止');}catch(e){toast(e.message,'error');}}",
        "async function stopSvc(id){try{await api(`/api/services/${id}/stop`,'POST');toast(id+' 已停止');}catch(e){toast(e.message,'error');}}\nasync function toggleAutostart(id,enabled){\n  try{await api(`/api/services/${id}/autostart`,'POST',{enabled});autostartMap[id]=enabled;toast(id+(enabled?' 开机自启已启用':' 开机自启已关闭'));}\n  catch(e){toast(e.message,'error');renderServices();}\n}",
    )
    print("5a. index.html — full autostart UI added from scratch")

# 5b. Also update loadServices to fetch autostart for ALL services (not just systemd)
if "systemdSvcs=services.filter" in html:
    # Replace systemd-only fetch with fetch for all services
    html = html.replace(
        "    // Fetch autostart status for systemd services\n    const systemdSvcs=services.filter(s=>s.type==='systemd');\n    await Promise.all(systemdSvcs.map(async s=>{",
        "    // Fetch autostart status for all services\n    await Promise.all(services.map(async s=>{",
    )
    print("5b. index.html — loadServices fetches autostart for ALL services")
elif "Fetch autostart status for" not in html:
    # The loadServices patch was already done differently or not at all
    print("5b. index.html — loadServices autostart fetch already updated or not needed")

with open(f"{BASE}/index.html", "w", encoding="utf-8") as f:
    f.write(html)
print("5c. index.html saved")

# ═══════════════════════════════════════════════════════════════════════
# 6. services.json — add autostart: true for currently-enabled systemd services
# ═══════════════════════════════════════════════════════════════════════

SJSON = "/home/manfred/ai-local/configs/services.json"
import json

with open(SJSON, "r", encoding="utf-8") as f:
    svc_data = json.load(f)

changed = False
for sid, svc in svc_data.get("services", {}).items():
    if "autostart" not in svc:
        # Default: existing systemd services get autostart=true (they already
        # had systemctl enable), others start as autostart=false
        default = svc.get("type") == "systemd"
        svc["autostart"] = default
        changed = True
        print(f"6. services.json — set {sid} autostart={default}")

if changed:
    with open(SJSON, "w", encoding="utf-8") as f:
        json.dump(svc_data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print("6. services.json saved with autostart defaults")
else:
    print("6. services.json — all services already have autostart field")

# ═══════════════════════════════════════════════════════════════════════
# 7. Copy patched index.html to static/ (the directory Manager serves from)
# ═══════════════════════════════════════════════════════════════════════

import shutil
static_index = f"{BASE}/static/index.html"
if os.path.exists(static_index):
    shutil.copy2(f"{BASE}/index.html", static_index)
    print("7. static/index.html synced from patched root index.html")
else:
    print("7. WARNING: static/ directory not found, index.html not copied to serving path")

print("\nALL PATCHES APPLIED — restart AI Runtime Manager to activate autostart_all()")
print("  sudo systemctl restart ai-runtime-manager")
