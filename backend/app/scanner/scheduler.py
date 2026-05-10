import asyncio
import logging
from datetime import datetime, timedelta
from sqlalchemy import select, delete
from app.database import async_session
from app.models.setting import Setting
from app.models.device import DeviceHistory
from app.scanner.planner import run_planner_scan, run_arp_only_scan
from app.scanner.dashboard import run_dashboard_scan
from app.scanner.utils import get_local_subnets

logger = logging.getLogger(__name__)

def _get_auto_scan_subnets():
    """Returns a list of CIDR subnets that are suitable for automatic scanning (non-virtual)."""
    all_subnets = get_local_subnets()
    return [s.subnet for s in all_subnets if not s.is_virtual]

class ScanScheduler:
    def __init__(self):
        self._task = None
        self._quick_task = None
        self._arp_task = None
        self._docker_task = None
        self._running = False

    async def start(self):
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        self._quick_task = asyncio.create_task(self._quick_loop())
        self._arp_task = asyncio.create_task(self._arp_loop())
        self._docker_task = asyncio.create_task(self._docker_loop())
        logger.info("Scan scheduler started (Full + Quick + ARP Turbo + Docker Sync)")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
        if self._quick_task:
            self._quick_task.cancel()
        if self._arp_task:
            self._arp_task.cancel()
        if self._docker_task:
            self._docker_task.cancel()
        
        # Wait for tasks to exit
        await asyncio.gather(self._task, self._quick_task, self._arp_task, self._docker_task, return_exceptions=True)
        logger.info("Scan scheduler stopped")

    async def _is_setup_complete(self) -> bool:
        """Checks if the system setup is marked as complete."""
        try:
            async with async_session() as db:
                result = await db.execute(select(Setting).where(Setting.key == "setup.complete"))
                setting = result.scalar_one_or_none()
                return setting is not None and setting.value == "true"
        except Exception:
            return False

    async def _loop(self):
        while self._running:
            try:
                if not await self._is_setup_complete():
                    await asyncio.sleep(10)
                    continue

                # Run cleanup first
                await self._clean_old_history()

                async with async_session() as db:
                    # Get interval from settings (in minutes)
                    result = await db.execute(select(Setting).where(Setting.key == "scan_interval"))
                    setting = result.scalar_one_or_none()
                    interval = int(setting.value) if setting and setting.value.isdigit() else 0

                    if interval > 0:
                        logger.info(f"Scheduled scan starting (Interval: {interval}m)")
                        
                        # Get subnets to scan (fallback to all if not set)
                        result = await db.execute(select(Setting).where(Setting.key == "scan_subnets"))
                        subnet_setting = result.scalar_one_or_none()
                        
                        if subnet_setting and subnet_setting.value:
                            subnets = [s.strip() for s in subnet_setting.value.split(",") if s.strip()]
                        else:
                            subnets = _get_auto_scan_subnets()

                        if subnets:
                            logger.info(f"Scheduled Full Scan (Dashboard) starting for: {subnets}")
                            await run_dashboard_scan(subnets)
                        
                        # Wait for the next interval
                        await asyncio.sleep(interval * 60)
                    else:
                        await asyncio.sleep(60)

            except Exception as e:
                logger.error(f"Error in scan scheduler loop: {e}")
                await asyncio.sleep(60)

    async def _arp_loop(self) -> None:
        """Passive ARP monitoring loop (Turbo Mode: 10s interval)."""
        logger.info("ARP Turbo loop started (Interval: 10s)")
        while self._running:
            if not await self._is_setup_complete():
                await asyncio.sleep(10)
                continue
            try:
                await run_arp_only_scan()
            except Exception as e:
                logger.error(f"ARP loop error: {e}")
            
            await asyncio.sleep(10)

    async def _quick_loop(self):
        """High-frequency status check for known devices."""
        while self._running:
            if not await self._is_setup_complete():
                await asyncio.sleep(10)
                continue
            try:
                # Get quick scan interval (default 300s / 5m)
                async with async_session() as db:
                    result = await db.execute(select(Setting).where(Setting.key == "quick_scan_interval"))
                    setting = result.scalar_one_or_none()
                    # Use provided value or 300 as default
                    interval = int(setting.value) if setting and setting.value.isdigit() else 300

                if interval > 0:
                    logger.info(f"Scheduled Quick Scan (Planner) starting (Interval: {interval}s)")
                    
                    # Detect subnets for quick scan
                    async with async_session() as db:
                        res = await db.execute(select(Setting).where(Setting.key == "scan_subnets"))
                        s_set = res.scalar_one_or_none()
                        subnets = [s.strip() for s in s_set.value.split(",") if s.strip()] if s_set and s_set.value else _get_auto_scan_subnets()
                    
                    if subnets:
                        await run_planner_scan(subnets)
                    
                    await asyncio.sleep(interval)
                else:
                    await asyncio.sleep(60)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in quick scan loop: {e}")
                await asyncio.sleep(60)

    async def _docker_loop(self):
        """Sync local Docker container status (1m interval)."""
        from app.services.docker_service import docker_service
        from app.scanner.sync import sync_docker_containers
        
        while self._running:
            if not await self._is_setup_complete():
                await asyncio.sleep(10)
                continue
            try:
                if docker_service.is_available():
                    containers = docker_service.get_local_containers()
                    if containers:
                        logger.info(f"Docker Sync: Syncing {len(containers)} local containers...")
                        await sync_docker_containers(containers)
                
                # Sleep for 1 minute
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in docker sync loop: {e}")
                await asyncio.sleep(60)

    async def _clean_old_history(self):
        """Delete history records older than the configured retention period."""
        try:
            async with async_session() as db:
                # Get retention period (in days)
                result = await db.execute(select(Setting).where(Setting.key == "history_retention_days"))
                setting = result.scalar_one_or_none()
                days = int(setting.value) if setting and setting.value.isdigit() else 7 # Default 7 days

                if days > 0:
                    cutoff = datetime.now() - timedelta(days=days)
                    await db.execute(delete(DeviceHistory).where(DeviceHistory.timestamp < cutoff))
                    await db.commit()
                    logger.info(f"Cleaned up history older than {days} days")
        except Exception as e:
            logger.error(f"Failed to clean up old history: {e}")

# Global instance
scheduler = ScanScheduler()
