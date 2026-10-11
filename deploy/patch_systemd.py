#!/usr/bin/env python3
"""Patch service_registry.py to add systemd service type support."""
import re

with open('/home/manfred/ai-local/services/manager/service_registry.py', 'r') as f:
    content = f.read()

# 1. In start_service, add systemd handling
old_build = '''        # Build command
        if scfg.type == ServiceType.LLAMA_CPP:
            cmd = self._build_llama_cmd(scfg, overrides)
        else:
            cmd = self._build_uvicorn_cmd(scfg, overrides)'''

new_build = '''        # Build command
        if scfg.type == ServiceType.SYSTEMD:
            return await self._start_systemd_service(service_id, scfg, state)
        elif scfg.type == ServiceType.LLAMA_CPP:
            cmd = self._build_llama_cmd(scfg, overrides)
        else:
            cmd = self._build_uvicorn_cmd(scfg, overrides)'''

content = content.replace(old_build, new_build)

# 2. In stop_service, add systemd handling before the process-based logic
old_stop = '''        proc = self._processes.pop(service_id, None)
        port = state.config.port if state.config else None'''

new_stop = '''        # Handle systemd services separately
        if state.config and state.config.type == ServiceType.SYSTEMD:
            return await self._stop_systemd_service(service_id, state.config, state)

        proc = self._processes.pop(service_id, None)
        port = state.config.port if state.config else None'''

content = content.replace(old_stop, new_stop)

# 3. Add systemd methods before health check section
systemd_methods = '''    # ------------------------------------------------------------------ #
    #  systemd service management (ComfyUI, etc.)
    # ------------------------------------------------------------------ #

    async def _start_systemd_service(
        self, service_id: str, scfg: ServiceConfig, state: ServiceState
    ) -> ServiceState:
        """Start a systemd-managed service via systemctl."""
        unit = scfg.systemd_unit or scfg.params.get("systemd_unit", "")
        if not unit:
            state.status = ServiceStatus.ERROR
            state.error_message = "No systemd_unit configured"
            await self._notify_change(state)
            raise ValueError("No systemd_unit configured")

        result = subprocess.run(
            ["sudo", "systemctl", "start", unit],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            state.status = ServiceStatus.ERROR
            state.error_message = result.stderr.strip() or "systemctl start failed"
            await self._notify_change(state)
            raise RuntimeError("systemctl start " + unit + " failed: " + result.stderr)

        state.status = ServiceStatus.RUNNING
        state.started_at = datetime.now(timezone.utc)
        task = asyncio.create_task(self._health_check_loop(service_id))
        self._health_tasks[service_id] = task
        logger.info("Started systemd service %s (%s)", service_id, unit)
        await self._notify_change(state)
        return state

    async def _stop_systemd_service(
        self, service_id: str, scfg: ServiceConfig, state: ServiceState
    ) -> ServiceState:
        """Stop a systemd-managed service via systemctl + GPU cleanup."""
        unit = scfg.systemd_unit or scfg.params.get("systemd_unit", "")
        if not unit:
            state.status = ServiceStatus.STOPPED
            await self._notify_change(state)
            return state

        result = subprocess.run(
            ["sudo", "systemctl", "stop", unit],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            logger.warning("systemctl stop %s failed: %s", unit, result.stderr)

        # Force-release GPU memory
        if scfg.port:
            await self._cleanup_gpu_memory(scfg.port)

        state.status = ServiceStatus.STOPPED
        state.pid = None
        state.started_at = None
        state.uptime_seconds = None
        logger.info("Stopped systemd service %s (%s)", service_id, unit)
        await self._notify_change(state)
        return state

'''

marker = "    # ------------------------------------------------------------------ #\n    #  Health checks"
content = content.replace(marker, systemd_methods + marker)

# 4. In _health_check_loop, add systemd branch
old_health = '''    async def _health_check_loop(self, service_id: str) -> None:
        state = self._states.get(service_id)
        if not state:
            return
        scfg = state.config
        if not scfg:
            return

        # For llama-cpp services, check process AND HTTP health
        if scfg.type == ServiceType.LLAMA_CPP:'''

new_health = '''    async def _health_check_loop(self, service_id: str) -> None:
        state = self._states.get(service_id)
        if not state:
            return
        scfg = state.config
        if not scfg:
            return

        # For systemd services, check systemctl is-active
        if scfg.type == ServiceType.SYSTEMD:
            unit = scfg.systemd_unit or scfg.params.get("systemd_unit", "")
            while True:
                try:
                    result = subprocess.run(
                        ["sudo", "systemctl", "is-active", unit],
                        capture_output=True, text=True, timeout=5,
                    )
                    is_active = result.stdout.strip() == "active"
                    if is_active and state.status != ServiceStatus.RUNNING:
                        state.status = ServiceStatus.RUNNING
                        await self._notify_change(state)
                    elif not is_active and state.status == ServiceStatus.RUNNING:
                        state.status = ServiceStatus.STOPPED
                        await self._notify_change(state)
                except Exception:
                    pass
                await asyncio.sleep(30)
            return

        # For llama-cpp services, check process AND HTTP health
        if scfg.type == ServiceType.LLAMA_CPP:'''

content = content.replace(old_health, new_health)

with open('/home/manfred/ai-local/services/manager/service_registry.py', 'w') as f:
    f.write(content)
print("PATCHED OK")
