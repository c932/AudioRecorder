#!/usr/bin/env python3
"""Add autostart (systemctl enable/disable) support to AI Runtime Manager."""

# 1. Patch service_registry.py — add set_autostart method
with open('/home/manfred/ai-local/services/manager/service_registry.py', 'r') as f:
    sr = f.read()

# Add set_autostart method before the health checks section
marker = "    # ------------------------------------------------------------------ #\n    #  Health checks"
autostart_method = '''    # ------------------------------------------------------------------ #
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
            return False

'''

sr = sr.replace(marker, autostart_method + marker)

with open('/home/manfred/ai-local/services/manager/service_registry.py', 'w') as f:
    f.write(sr)
print("service_registry.py patched")

# 2. Patch main.py — add autostart API endpoint
with open('/home/manfred/ai-local/services/manager/main.py', 'r') as f:
    main = f.read()

# Add autostart endpoint after the stop endpoint
# Find a good insertion point — after the stop endpoint
insert_after = '''        state = await registry.stop_service(service_id, force=req.force)
        return _state_response(state, service_id)'''

autostart_endpoint = '''        state = await registry.stop_service(service_id, force=req.force)
        return _state_response(state, service_id)


class AutostartRequest(BaseModel):
    enabled: bool


@app.post("/api/services/{service_id}/autostart")
async def set_autostart(service_id: str, req: AutostartRequest, _: dict = Depends(get_current_user)):
    """Enable or disable systemd autostart for a service."""
    try:
        state = await registry.set_autostart(service_id, req.enabled)
        return {"success": True, "service_id": service_id, "autostart": req.enabled}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/services/{service_id}/autostart")
async def get_autostart(service_id: str, _: dict = Depends(get_current_user)):
    """Check if a service has autostart enabled."""
    return {"service_id": service_id, "autostart": registry.get_autostart(service_id)}'''

main = main.replace(insert_after, autostart_endpoint)

with open('/home/manfred/ai-local/services/manager/main.py', 'w') as f:
    f.write(main)
print("main.py patched")
