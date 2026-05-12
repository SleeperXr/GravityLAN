import logging
import docker
import os
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

class DockerService:
    """Service for discovering and monitoring local Docker containers via the Docker socket."""
    
    def __init__(self):
        self.client: Optional[docker.DockerClient] = None
        self.socket_path = "/var/run/docker.sock"
        self._is_available = False
        self.host_ips: set[str] = set()
        
        if os.path.exists(self.socket_path):
            try:
                self.client = docker.DockerClient(base_url=f"unix://{self.socket_path}")
                self.client.ping()
                self._is_available = True
                self._load_host_info()
                logger.info("Docker Service: Successfully connected to Docker socket.")
            except Exception as e:
                logger.warning(f"Docker Service: Socket found but connection failed: {e}")
        else:
            logger.info("Docker Service: No Docker socket found at /var/run/docker.sock. Local container discovery disabled.")

    def _load_host_info(self):
        """Loads host information like IPs from Docker."""
        if not self.client: return
        try:
            # We can get the node's IPs via netifaces if running in host mode,
            # or try to get it from docker info.
            # A simple way for Unraid is to check the default bridge gateway and 
            # assume the host has the same subnets.
            # But the most reliable way is to just use the bridge gateway as a trigger.
            pass
        except Exception:
            pass

    def is_available(self) -> bool:
        """Check if the Docker service is connected and available."""
        return self._is_available

    def get_local_containers(self) -> List[Dict]:
        """
        Fetch a list of all local containers with their IPs and status.
        
        Returns:
            List[Dict]: List of dicts with {id, name, ip, status, image}
        """
        if not self._is_available or not self.client:
            return []

        containers_data = []
        try:
            containers = self.client.containers.list(all=True)
            for container in containers:
                networks = container.attrs.get('NetworkSettings', {}).get('Networks', {})
                ips = []
                for net_name, net_data in networks.items():
                    ip = net_data.get('IPAddress')
                    if ip:
                        ips.append(ip)
                
                # If it's host mode, it might not have an IP in NetworkSettings
                if not ips and container.attrs.get('HostConfig', {}).get('NetworkMode') == 'host':
                    # In host mode, it technically has the host's IP, but we don't want to 
                    # map everything to the host IP. 
                    pass

                containers_data.append({
                    "id": container.short_id,
                    "name": container.name,
                    "ips": ips,
                    "status": container.status, # running, exited, paused, etc.
                    "image": container.image.tags[0] if container.image.tags else "unknown",
                    "state": container.attrs.get('State', {})
                })
        except Exception as e:
            logger.error(f"Docker Service: Error fetching containers: {e}")
            
        return containers_data

    def get_container_status_by_ip(self, ip: str) -> Optional[str]:
        """
        Find a container by its IP and return its status.
        
        Args:
            ip (str): The IP address to look for.
            
        Returns:
            Optional[str]: The container status (e.g., 'running') or None if not found.
        """
        containers = self.get_local_containers()
        for container in containers:
            if ip in container["ips"]:
                return container["status"]
        return None

    def get_bridge_gateway(self) -> Optional[str]:
        """Gets the gateway IP of the default Docker bridge network."""
        if not self._is_available or not self.client:
            return None
        try:
            net = self.client.networks.get("bridge")
            ipam = net.attrs.get("IPAM", {}).get("Config", [])
            if ipam:
                return ipam[0].get("Gateway")
        except Exception:
            pass
        return None

# Singleton instance
docker_service = DockerService()
