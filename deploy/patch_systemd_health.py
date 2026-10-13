#!/usr/bin/env python3
"""Patch service_registry to start health checks for systemd services on init."""

with open('/home/manfred/ai-local/services/manager/service_registry.py', 'r') as f:
    content = f.read()

# Add a method to start health checks for systemd services
# Insert after _refresh_configs method
old_refresh_end = """            else:
                self._states[sid].config = scfg"""

new_refresh_end = """            else:
                self._states[sid].config = scfg

        # Start health checks for systemd services (they're managed externally)
        import asyncio as _asyncio
        try:
            loop = _asyncio.get_event_loop()
            if loop.is_running():
                for sid, state in self._states.items():
                    if (state.config and state.config.type == ServiceType.SYSTEMD
                            and sid not in self._health_tasks):
                        task = loop.create_task(self._health_check_loop(sid))
                        self._health_tasks[sid] = task
                        logger.info("Started health check for systemd service: %s", sid)
        except RuntimeError:
            pass  # No event loop yet, will be called again later"""

content = content.replace(old_refresh_end, new_refresh_end)

with open('/home/manfred/ai-local/services/manager/service_registry.py', 'w') as f:
    f.write(content)
print("PATCHED OK")
