#!/usr/bin/env python3
"""Fix health check loop to handle systemd services properly."""

with open('/home/manfred/ai-local/services/manager/service_registry.py', 'r') as f:
    content = f.read()

# Replace the entire _health_check_loop with a version that handles systemd
old_health = """    async def _health_check_loop(self, service_id: str) -> None:
        state = self._states.get(service_id)
        if not state:
            return

        scfg = state.config
        if not scfg:
            return

        url = f"http://127.0.0.1:{scfg.port}{scfg.health_endpoint}"
        deadline = time.monotonic() + 180  # 3 min timeout

        while time.monotonic() < deadline:
            proc = self._processes.get(service_id)
            if not proc or proc.poll() is not None:
                state.status = ServiceStatus.ERROR
                state.error_message = "Process exited during startup"
                await self._notify_change(state)
                return

            try:
                req = Request(url, method="GET")
                with urlopen(req, timeout=3):
                    state.status = ServiceStatus.RUNNING
                    state.health = "ok"
                    await self._notify_change(state)
                    logger.info("Service %s is healthy", service_id)
                    return
            except Exception:
                pass

            await asyncio.sleep(2)

        # Timeout
        state.status = ServiceStatus.ERROR
        state.error_message = "Health check timeout (180s)"
        await self._notify_change(state)"""

new_health = """    async def _health_check_loop(self, service_id: str) -> None:
        state = self._states.get(service_id)
        if not state:
            return

        scfg = state.config
        if not scfg:
            return

        # systemd services: poll systemctl is-active + HTTP health
        if scfg.type == ServiceType.SYSTEMD:
            unit = scfg.systemd_unit or scfg.params.get("systemd_unit", "")
            while True:
                try:
                    result = subprocess.run(
                        ["sudo", "systemctl", "is-active", unit],
                        capture_output=True, text=True, timeout=5,
                    )
                    is_active = result.stdout.strip() == "active"
                    if is_active:
                        # Also check HTTP health
                        url = f"http://127.0.0.1:{scfg.port}{scfg.health_endpoint}"
                        try:
                            req = Request(url, method="GET")
                            with urlopen(req, timeout=3):
                                state.status = ServiceStatus.RUNNING
                                state.health = "ok"
                                state.error_message = None
                                await self._notify_change(state)
                        except Exception:
                            # Service active but HTTP not ready yet
                            state.status = ServiceStatus.STARTING
                            await self._notify_change(state)
                    else:
                        if state.status == ServiceStatus.RUNNING:
                            state.status = ServiceStatus.STOPPED
                            state.health = None
                            await self._notify_change(state)
                except Exception as e:
                    logger.debug("systemd health check error for %s: %s", service_id, e)
                await asyncio.sleep(10)
            return

        # Non-systemd services: check process + HTTP health
        url = f"http://127.0.0.1:{scfg.port}{scfg.health_endpoint}"
        deadline = time.monotonic() + 180  # 3 min timeout

        while time.monotonic() < deadline:
            proc = self._processes.get(service_id)
            if not proc or proc.poll() is not None:
                state.status = ServiceStatus.ERROR
                state.error_message = "Process exited during startup"
                await self._notify_change(state)
                return

            try:
                req = Request(url, method="GET")
                with urlopen(req, timeout=3):
                    state.status = ServiceStatus.RUNNING
                    state.health = "ok"
                    await self._notify_change(state)
                    logger.info("Service %s is healthy", service_id)
                    return
            except Exception:
                pass

            await asyncio.sleep(2)

        # Timeout
        state.status = ServiceStatus.ERROR
        state.error_message = "Health check timeout (180s)"
        await self._notify_change(state)"""

content = content.replace(old_health, new_health)

with open('/home/manfred/ai-local/services/manager/service_registry.py', 'w') as f:
    f.write(content)
print("PATCHED OK")
