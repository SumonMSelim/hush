"""Write fixtures/alerts.json: Grafana webhook payloads modelled on a real homelab's rules.

Each entry carries `expect`, the on-call engineer's own verdict, used by replay and bench
to score the gate. Verdicts: page (wake a human now), review (worth a brief, no page),
drop (noise or information, nobody needs it at 3am).
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

T0 = datetime(2026, 10, 22, 3, 0, tzinfo=timezone.utc)


def alert(name, severity, summary, description, expect, labels=None, status="firing", minutes=0):
    start = T0 + timedelta(minutes=minutes)
    lab = {"alertname": name, "severity": severity, "grafana_folder": "Homelab", **(labels or {})}
    return {
        "receiver": "hush",
        "status": status,
        "alerts": [
            {
                "status": status,
                "labels": lab,
                "annotations": {"summary": summary, "description": description},
                "startsAt": start.isoformat(),
                "endsAt": (start + timedelta(minutes=4)).isoformat() if status == "resolved" else "0001-01-01T00:00:00Z",
                "fingerprint": f"{abs(hash((name, summary, minutes))):016x}",
            }
        ],
        "commonLabels": lab,
        "title": f"[{status.upper()}] {name}",
        "expect": expect,
    }


A = []
# --- outages: page
A.append(alert("Web service down", "critical", "immich.mol.la is down", "immich.mol.la (https://immich.mol.la) not answering HTTP for 5m", "page", {"instance": "immich.mol.la", "job": "blackbox"}))
A.append(alert("Web service down", "critical", "outline.mol.la is down", "outline.mol.la (https://outline.mol.la) not answering HTTP for 5m", "page", {"instance": "outline.mol.la", "job": "blackbox"}))
A.append(alert("Scrape target down", "critical", "node/pve1:9100 is not scraped", "node target pve1:9100 has been unreachable or missing for 5m (host down, tailnet link lost, or exporter dead)", "page", {"instance": "pve1:9100", "job": "node"}))
A.append(alert("Timothy backend unhealthy", "critical", "timothy health probe failing", "https://timothy.mol.la/healthz returned non-200 for 5m", "page", {"instance": "timothy.mol.la", "job": "blackbox-timothy-health"}))
A.append(alert("PostgreSQL down", "critical", "postgresql on db1 is not accepting connections", "pg_up == 0 on db1 for 3m; immich and outline depend on it", "page", {"instance": "db1:9187", "job": "postgres"}))
A.append(alert("Proxmox node offline", "critical", "pve2 is offline", "pve_node_up{node=\"pve2\"} == 0 for 5m; 6 LXCs live on this node", "page", {"instance": "pve2", "job": "pve"}))
A.append(alert("Caddy reverse proxy down", "critical", "caddy admin API unreachable", "caddy on edge1 not answering for 5m; every public site goes through it", "page", {"instance": "edge1:2019", "job": "caddy"}))
A.append(alert("Vault sealed", "critical", "vault is sealed", "vault_core_unsealed == 0 on vault1 for 2m; services cannot fetch secrets on restart", "page", {"instance": "vault1:8200", "job": "vault"}))
A.append(alert("Root filesystem nearly full", "critical", "db1 root fs at 97%", "node_filesystem_avail_bytes on db1 / is 3% free and falling 1%/h; postgres will stop accepting writes", "page", {"instance": "db1", "mountpoint": "/"}))
A.append(alert("Backup failed", "critical", "nightly restic backup to B2 failed", "restic backup exit code 1 on backup1: repository lock held by another process; second consecutive failure", "page", {"instance": "backup1", "job": "restic"}))
A.append(alert("AdGuard DNS down", "critical", "adguard not answering DNS", "dns probe to 192.168.178.10:53 failing for 5m; whole LAN loses name resolution", "page", {"instance": "adguard", "job": "blackbox-dns"}))
A.append(alert("SSH brute force", "warning", "412 failed ssh logins on edge1 in 10m", "sshd auth failures from 14 source IPs in 10m on the public edge host; fail2ban is not banning", "page", {"instance": "edge1", "job": "loki"}))
A.append(alert("Memory pressure", "critical", "OOM killer active on media1", "3 OOM kills in 10m on media1 (jellyfin, navidrome); available memory 2%", "page", {"instance": "media1", "job": "node"}))
A.append(alert("TLS certificate expiring", "critical", "cert for *.mol.la expires in 18h", "probe_ssl_earliest_cert_expiry for *.mol.la is 18h away; renewal cron has failed twice", "page", {"instance": "mol.la", "job": "blackbox"}))

# --- worth a look in the morning: review
A.append(alert("Root filesystem nearly full", "warning", "media1 root fs at 82%", "node_filesystem_avail_bytes on media1 / is 18% free, stable over 24h", "review", {"instance": "media1", "mountpoint": "/"}))
A.append(alert("High CPU", "warning", "pve1 CPU above 85% for 15m", "jellyfin transcoding two streams; load average 14 on 16 cores", "review", {"instance": "pve1", "job": "node"}))
A.append(alert("TLS certificate expiring", "warning", "cert for jellyfin.mol.la expires in 12 days", "probe_ssl_earliest_cert_expiry is 12d away; auto-renewal scheduled in 2d", "review", {"instance": "jellyfin.mol.la", "job": "blackbox"}))
A.append(alert("Docker image pull failures", "warning", "watchtower failed to pull 2 images", "ghcr.io rate limit hit while pulling draftly and timothy images; will retry in 6h", "review", {"instance": "apps1", "job": "watchtower"}))
A.append(alert("Redis memory high", "warning", "redis on apps1 at 78% of maxmemory", "used_memory 1.56GB of 2GB; eviction policy allkeys-lru is active", "review", {"instance": "apps1:6379", "job": "redis"}))
A.append(alert("Slow PostgreSQL queries", "warning", "p99 query latency 2.4s on db1", "pg_stat_statements shows immich thumbnail job queries above 2s for 20m", "review", {"instance": "db1:9187", "job": "postgres"}))
A.append(alert("Unattended upgrades pending reboot", "warning", "4 hosts need a reboot", "kernel update applied on pve1, pve2, db1, apps1; reboot required", "review", {"instance": "fleet", "job": "node"}))
A.append(alert("Tailscale node offline", "warning", "laptop-sumon left the tailnet", "tailscale node laptop-sumon last seen 3h ago; it is a client device, not a server", "review", {"instance": "laptop-sumon", "job": "tailscale"}))
A.append(alert("SMART warning", "warning", "sda on pve2 reports 3 reallocated sectors", "smartmon_reallocated_sector_ct increased from 0 to 3 in 7d on a ZFS mirror member; pool is ONLINE", "review", {"instance": "pve2", "device": "sda"}))
A.append(alert("GitHub runner idle", "warning", "self-hosted runner offline 2h", "gh runner on build1 not polling; no jobs queued", "review", {"instance": "build1", "job": "github-runner"}))
A.append(alert("Immich job queue backlog", "warning", "12k thumbnail jobs queued", "immich microservices backlog grew after bulk import; processing at 40/min", "review", {"instance": "immich", "job": "immich"}))
A.append(alert("Memory pressure", "warning", "apps1 at 88% memory", "available memory 12% on apps1 for 30m, no OOM kills, swap unused", "review", {"instance": "apps1", "job": "node"}))

# --- noise and information: drop
A.append(alert("Web service down", "critical", "immich.mol.la is down", "immich.mol.la (https://immich.mol.la) not answering HTTP for 5m", "drop", {"instance": "immich.mol.la", "job": "blackbox"}, status="resolved", minutes=6))
A.append(alert("Scrape target down", "critical", "node/laptop-sumon:9100 is not scraped", "node target laptop-sumon:9100 has been unreachable or missing for 5m (host down, tailnet link lost, or exporter dead)", "drop", {"instance": "laptop-sumon:9100", "job": "node"}))
A.append(alert("Scrape target down", "critical", "cadvisor/dev-lxc:8080 is not scraped", "cadvisor target dev-lxc:8080 has been unreachable or missing for 5m; dev-lxc is a throwaway dev container", "drop", {"instance": "dev-lxc:8080", "job": "cadvisor", "env": "dev"}))
A.append(alert("High CPU", "warning", "pve1 CPU above 85% for 15m", "jellyfin transcoding; load returned to normal", "drop", {"instance": "pve1", "job": "node"}, status="resolved", minutes=20))
A.append(alert("Backup finished", "info", "nightly restic backup completed", "restic backup on backup1 finished in 14m, 2.1GB added, snapshot 7f3a9c", "drop", {"instance": "backup1", "job": "restic"}))
A.append(alert("Docker prune completed", "info", "weekly docker prune freed 18GB", "deploy_docker_prune ran on apps1, media1; 18.4GB reclaimed", "drop", {"instance": "fleet", "job": "cron"}))
A.append(alert("Test alert", "info", "TestAlert from Grafana", "This is a test notification sent from the Grafana contact point editor", "drop", {"instance": "grafana", "job": "grafana"}))
A.append(alert("Jellyfin stream started", "info", "2 active streams on jellyfin", "jellyfin_active_streams == 2 (direct play)", "drop", {"instance": "media1", "job": "jellyfin"}))
A.append(alert("Web service down", "critical", "draftly.mol.la is down", "draftly.mol.la not answering HTTP for 5m", "drop", {"instance": "draftly.mol.la", "job": "blackbox"}, status="resolved", minutes=9))
A.append(alert("Package upgrades available", "info", "37 packages upgradable across the fleet", "apt lists 37 upgradable packages; none are security updates", "drop", {"instance": "fleet", "job": "node"}))
A.append(alert("Tailscale node offline", "warning", "phone-sumon left the tailnet", "tailscale node phone-sumon last seen 10m ago; mobile client", "drop", {"instance": "phone-sumon", "job": "tailscale"}))
A.append(alert("Blackbox probe flapping", "warning", "navidrome.mol.la probe flapped 6 times in 30m", "probe_success toggled 6 times; each outage under 60s; site is up now", "drop", {"instance": "navidrome.mol.la", "job": "blackbox"}))
A.append(alert("Grafana datasource health", "info", "all 6 datasources healthy", "scheduled datasource health check passed", "drop", {"instance": "grafana", "job": "grafana"}))
A.append(alert("Scrape target down", "critical", "node/pve1:9100 is not scraped", "node target pve1:9100 reachable again", "drop", {"instance": "pve1:9100", "job": "node"}, status="resolved", minutes=12))

Path(__file__).with_name("alerts.json").write_text(json.dumps(A, indent=1) + "\n")
print(len(A), "alerts;", {v: sum(1 for a in A if a["expect"] == v) for v in ("page", "review", "drop")})
