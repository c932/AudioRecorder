#!/usr/bin/env python3
"""Patch start_patrol to also start health checks for systemd services."""

with open('/home/manfred/ai-local/services/manager/service_registry.py', 'r') as f:
    content = f.read()

old_patrol = """    async def start_patrol(self) -> None:
        self._patrol_task = asyncio.create_task(self._patrol_loop())"""

new_patrol = """    async def start_patrol(self) -> None:
        self._patrol_task = asyncio.create_task(self._patrol_loop())
        # Start health checks for systemd services (managed externally by systemd)
        for sid, state in self._states.items():
            if (state.config and state.config.type == ServiceType.SYSTEMD
                    and sid not in self._health_tasks):
                task = asyncio.create_task(self._health_check_loop(sid))
                self._health_tasks[sid] = task
                logger.info("Started health check for systemd service: %s", sid)"""

content = content.replace(old_patrol, new_patrol)

with open('/home/manfred/ai-local/services/manager/service_registry.py', 'w') as f:
    f.write(content)
print("PATCHED OK")
