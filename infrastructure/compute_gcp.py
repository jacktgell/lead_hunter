import os
import time
import requests
import subprocess
import shutil
import socket
from typing import Optional, Final

from google.cloud import compute_v1
from core.interfaces import IComputeManager
from core.config import GcpConfig
from core.logger import get_logger

logger = get_logger(__name__)


class GcpInfrastructureError(Exception):
    """Raised when GCP resource provisioning or state resolution fails."""
    pass


class TunnelConnectionError(Exception):
    """Raised when the IAP tunnel fails to bind or connect to the remote backend."""
    pass


class GcpConstants:
    """Centralized magic numbers and strings for GCP infrastructure."""
    IAP_SOURCE_RANGE: Final[str] = "35.235.240.0/20"
    DEFAULT_FIREWALL_RULE: Final[str] = "allow-iap-to-ollama"
    DEFAULT_NETWORK_TAG: Final[str] = "ollama-api"
    BOOT_TIMEOUT_SEC: Final[int] = 240
    POLL_INTERVAL_SEC: Final[int] = 5
    LOCAL_BIND_IP: Final[str] = "127.0.0.1"


class GcpOllamaManager(IComputeManager):
    """
    Manages the lifecycle and tunneling for a remote GCP Ollama instance.
    Ensures the instance is running, tagged, firewalled, and tunneled locally.
    """

    def __init__(self, config: GcpConfig) -> None:
        self.config = config
        self.instances_client = compute_v1.InstancesClient()
        self.firewalls_client = compute_v1.FirewallsClient()
        self.tunnel_process: Optional[subprocess.Popen] = None
        self.active_local_port: Optional[int] = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.shutdown()

    def ensure_infrastructure_ready(self) -> str:
        """
        Orchestrates the verification and provisioning of the GCP environment.

        Returns:
            str: The strictly formatted IPv4 local host URL for the tunneled API.

        Raises:
            GcpInfrastructureError: If the instance fails to boot.
            TunnelConnectionError: If the tunnel cannot be established.
        """
        logger.info(f"Verifying GCP instance: {self.config.instance_name} in {self.config.zone}")

        instance = self._wait_for_running_state()
        self._ensure_iap_firewall_rule()
        self._ensure_instance_tags(instance)

        self.active_local_port = self._establish_iap_tunnel()

        # Strict IPv4 enforcement to bypass OS-level IPv6 'localhost' resolution inconsistencies
        host_url = f"http://{GcpConstants.LOCAL_BIND_IP}:{self.active_local_port}"
        self._wait_for_ollama(host_url)

        return host_url

    def _wait_for_running_state(self) -> compute_v1.Instance:
        """Polls the GCP API until the instance is RUNNING or the timeout is reached."""
        start_time = time.time()

        while True:
            if time.time() - start_time > GcpConstants.BOOT_TIMEOUT_SEC:
                raise GcpInfrastructureError(
                    f"Instance failed to reach RUNNING state within {GcpConstants.BOOT_TIMEOUT_SEC} seconds."
                )

            instance = self.instances_client.get(
                project=self.config.project_id,
                zone=self.config.zone,
                instance=self.config.instance_name
            )

            status = instance.status

            if status == compute_v1.Instance.Status.RUNNING.name:
                logger.info("GCP instance is RUNNING.")
                return instance

            if status in (compute_v1.Instance.Status.STOPPING.name, compute_v1.Instance.Status.SUSPENDING.name):
                logger.info(f"Instance is currently {status}. Waiting for termination...")

            elif status == compute_v1.Instance.Status.TERMINATED.name:
                logger.info("Instance is TERMINATED. Issuing boot command...")
                operation = self.instances_client.start(
                    project=self.config.project_id,
                    zone=self.config.zone,
                    instance=self.config.instance_name
                )
                operation.result()
                logger.info("Boot operation acknowledged. Awaiting OS provisioning...")

            elif status in (compute_v1.Instance.Status.PROVISIONING.name, compute_v1.Instance.Status.STAGING.name):
                logger.info(f"Instance state: {status}. Awaiting RUNNING state...")

            else:
                logger.warning(f"Unhandled instance state detected: {status}. Attempting to proceed.")
                return instance

            time.sleep(GcpConstants.POLL_INTERVAL_SEC)

    def _is_port_in_use(self, port: int) -> bool:
        """Verifies if a specific local IPv4 port is currently bound."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            return sock.connect_ex((GcpConstants.LOCAL_BIND_IP, port)) == 0

    def _ensure_iap_firewall_rule(self) -> None:
        """Idempotently ensures the VPC firewall rule exists for IAP tunneling."""
        logger.info("Verifying VPC firewall rule for IAP ingress...")

        try:
            self.firewalls_client.get(
                project=self.config.project_id,
                firewall=GcpConstants.DEFAULT_FIREWALL_RULE
            )
            logger.debug("IAP firewall rule verified.")
            return
        except Exception:
            # Assuming NotFound or equivalent; proceed to create the rule
            logger.info("Firewall rule not found. Provisioning new rule...")

        try:
            firewall_rule = compute_v1.Firewall(
                name=GcpConstants.DEFAULT_FIREWALL_RULE,
                direction=compute_v1.Firewall.Direction.INGRESS.name,
                allowed=[compute_v1.Allowed(I_p_protocol="tcp", ports=[str(self.config.default_port)])],
                source_ranges=[GcpConstants.IAP_SOURCE_RANGE],
                target_tags=[GcpConstants.DEFAULT_NETWORK_TAG]
            )
            operation = self.firewalls_client.insert(
                project=self.config.project_id,
                firewall_resource=firewall_rule
            )
            operation.result()
            logger.info("IAP Firewall rule provisioned successfully.")
        except Exception as e:
            raise GcpInfrastructureError(f"Failed to provision firewall rule: {str(e)}")

    def _ensure_instance_tags(self, instance: compute_v1.Instance) -> None:
        """Verifies and patches network tags required by the firewall rule."""
        current_tags = list(instance.tags.items) if instance.tags.items else []

        if GcpConstants.DEFAULT_NETWORK_TAG not in current_tags:
            logger.info(f"Applying '{GcpConstants.DEFAULT_NETWORK_TAG}' network tag to instance...")
            current_tags.append(GcpConstants.DEFAULT_NETWORK_TAG)

            tags_obj = compute_v1.Tags(items=current_tags, fingerprint=instance.tags.fingerprint)
            operation = self.instances_client.set_tags(
                project=self.config.project_id,
                zone=self.config.zone,
                instance=self.config.instance_name,
                tags_resource=tags_obj
            )
            operation.result()
            logger.info("Network tag applied successfully.")
        else:
            logger.debug("Required network tags are already present.")

    def _establish_iap_tunnel(self) -> int:
        """
        Executes the Google Cloud SDK process to establish a secure TCP tunnel.
        Dynamically allocates ports to avoid zombie process conflicts.
        """
        default_port = self.config.default_port

        if self._is_port_in_use(default_port):
            try:
                # Active health check on the occupied port
                target = f"http://{GcpConstants.LOCAL_BIND_IP}:{default_port}/api/tags"
                if requests.get(target, timeout=3).status_code == 200:
                    logger.info("Live Ollama API detected on default port. Bypassing tunnel creation.")
                    return default_port
            except requests.exceptions.RequestException:
                logger.warning(f"Port {default_port} is unresponsive. Falling back to dynamic allocation.")

        local_port = default_port
        while self._is_port_in_use(local_port):
            local_port += 1

        logger.info(f"Allocating port {local_port} for the IAP tunnel...")

        gcloud_cmd = "gcloud.cmd" if os.name == 'nt' else "gcloud"
        if not shutil.which(gcloud_cmd):
            raise GcpInfrastructureError(f"Dependency missing: Could not find '{gcloud_cmd}' in system PATH.")

        cmd = [
            gcloud_cmd, "compute", "start-iap-tunnel",
            self.config.instance_name, str(self.config.default_port),
            f"--local-host-port={GcpConstants.LOCAL_BIND_IP}:{local_port}",
            f"--zone={self.config.zone}",
            f"--project={self.config.project_id}",
            "--quiet"
        ]

        # Hide the subprocess console window on Windows machines
        kwargs = {'stdout': subprocess.DEVNULL, 'stderr': subprocess.PIPE}
        if os.name == 'nt':
            kwargs['creationflags'] = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)

        max_tunnel_retries = 5
        for attempt in range(1, max_tunnel_retries + 1):
            try:
                logger.info(f"Establishing IAP tunnel (Attempt {attempt}/{max_tunnel_retries})...")
                self.tunnel_process = subprocess.Popen(cmd, **kwargs)
                time.sleep(self.config.tunnel_warmup_sec)

                if self.tunnel_process.poll() is not None:
                    _, stderr_bytes = self.tunnel_process.communicate()
                    error_msg = stderr_bytes.decode('utf-8').strip() if stderr_bytes else "No stderr output."

                    if "4003" in error_msg or "failed to connect to backend" in error_msg.lower():
                        logger.warning("Connection refused by backend. OS services likely initializing...")
                        if attempt < max_tunnel_retries:
                            time.sleep(10)
                            continue
                        raise TunnelConnectionError(f"Backend refused connection after {max_tunnel_retries} attempts.")

                    raise TunnelConnectionError(f"Process crashed (Code {self.tunnel_process.returncode}): {error_msg}")

                logger.info(f"IAP tunnel secured on {GcpConstants.LOCAL_BIND_IP}:{local_port}.")
                return local_port

            except Exception as e:
                if attempt == max_tunnel_retries:
                    logger.error(f"Exhausted tunnel retry budget: {str(e)}", exc_info=True)
                    raise TunnelConnectionError(str(e))

    def _wait_for_ollama(self, host_url: str) -> None:
        """Polls the remote Ollama API through the tunnel to guarantee inference readiness."""
        target_endpoint = f"{host_url}/api/tags"
        logger.info(f"Awaiting Ollama API readiness at {target_endpoint}...")

        max_retries = max(self.config.api_max_retries, 20)

        for attempt in range(1, max_retries + 1):
            try:
                if requests.get(target_endpoint, timeout=5).status_code == 200:
                    logger.info("Ollama API is fully responsive.")
                    return
                time.sleep(self.config.api_poll_delay_sec)

            except requests.exceptions.ConnectionError:
                logger.debug(f"[{attempt}/{max_retries}] Connection Refused: Backend service booting...")
                time.sleep(self.config.api_poll_delay_sec)
            except requests.exceptions.Timeout:
                logger.debug(f"[{attempt}/{max_retries}] Timeout: Model likely loading into VRAM...")
                time.sleep(self.config.api_poll_delay_sec)
            except Exception as e:
                raise GcpInfrastructureError(f"Unexpected error during API polling: {str(e)}")

        raise TimeoutError(f"Ollama API failed to respond after {max_retries} attempts.")

    def shutdown(self) -> None:
        """Gracefully terminates the local tunnel process and stops the remote GCP instance."""
        if self.tunnel_process:
            logger.info("Terminating local IAP tunnel process...")
            self.tunnel_process.terminate()
            try:
                self.tunnel_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logger.warning("Tunnel process did not terminate gracefully. Forcing kill.")
                self.tunnel_process.kill()
            self.tunnel_process = None

        logger.info(f"Dispatching shutdown command to GCP instance: {self.config.instance_name}...")
        try:
            self.instances_client.stop(
                project=self.config.project_id,
                zone=self.config.zone,
                instance=self.config.instance_name
            )
            logger.info("Instance shutdown command acknowledged.")
        except Exception as e:
            logger.error(f"Failed to dispatch shutdown command: {str(e)}", exc_info=True)