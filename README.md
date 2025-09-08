#PROJECTS LINKS
1)https://github.com/sandeepbikkana/self-heal-project1
2)https://github.com/sandeepbikkana/observability-stack-proj2
3)https://github.com/sandeepbikkana/CICD-GitHubActions-locally-proj4
4)https://github.com/sandeepbikkana/k3s-Istio-Proj7



# Self‑Healing NGINX on AWS (Prometheus + Alertmanager + Ansible)

This guide sets up a **self‑healing** stack where Prometheus detects failures, Alertmanager sends a webhook, a Flask service receives it, and an **Ansible playbook restarts your NGINX Docker container**.

Works on a single **Ubuntu EC2** instance with Docker Compose.

---

## 0) Architecture

```
NGINX (Docker)  ← probed by Blackbox
         ↑
Prometheus (Docker) — rules fire (NginxDown, HighCPU)
         ↓
Alertmanager (Docker) — sends POST → Webhook (Flask on host)
         ↓
Webhook (systemd, host) — runs run_ansible.sh → Ansible playbook
         ↓
Ansible (host) — docker-compose restart nginx
```

---

## 1) Prerequisites

* Ubuntu 22.04+ EC2
* Security Group: allow **22/tcp**, **80/tcp** (optional for demo), **9090/tcp** (Prometheus UI – restrict to your IP), **9093/tcp** (Alertmanager UI – restrict to your IP). Port **5001** is only needed from the EC2/containers → host (not public).
* Packages

  ```bash
  sudo apt update
  # Docker & Compose
  sudo apt install -y docker.io docker-compose
  sudo usermod -aG docker $USER
  newgrp docker

  # Python, pip, Ansible, Flask
  sudo apt install -y python3-pip ansible
  pip3 install --user flask
  ```

  > If you see Ansible/Jinja warnings later, they’re harmless. You can silence them by aligning versions (see Troubleshooting).

---

## 2) Directory Layout

We’ll keep everything under **/home/ubuntu/self-heal**.

```bash
mkdir -p /home/ubuntu/self-heal/{prometheus,alertmanager}
cd /home/ubuntu/self-heal
```

Final layout:

```
self-heal/
├─ docker-compose.yml
├─ prometheus/
│  ├─ prometheus.yml
│  └─ alert.rules.yml
├─ alertmanager/
│  └─ alertmanager.yml
├─ webhook.py
├─ run_ansible.sh
└─ heal.yml
```

---

## 3) docker-compose.yml

Create **/home/ubuntu/self-heal/docker-compose.yml**

```yaml
yaml
version: "3.8"

services:
  nginx:
    image: nginx:latest
    container_name: nginx
    ports:
      - "80:80"
    restart: unless-stopped

  prometheus:
    image: prom/prometheus:v2.54.1
    container_name: prometheus
    volumes:
      - ./prometheus/prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - ./prometheus/alert.rules.yml:/etc/prometheus/alert.rules.yml:ro
    command:
      - --config.file=/etc/prometheus/prometheus.yml
      - --storage.tsdb.path=/prometheus
    ports:
      - "9090:9090"
    depends_on:
      - blackbox
      - node-exporter
      - nginx
    restart: unless-stopped

  alertmanager:
    image: prom/alertmanager:v0.28.0
    container_name: alertmanager
    volumes:
      - ./alertmanager/alertmanager.yml:/etc/alertmanager/alertmanager.yml:ro
    command:
      - --config.file=/etc/alertmanager/alertmanager.yml
    ports:
      - "9093:9093"
    depends_on:
      - prometheus
    restart: unless-stopped

  blackbox:
    image: prom/blackbox-exporter:v0.25.0
    container_name: blackbox
    ports:
      - "9115:9115"
    restart: unless-stopped

  node-exporter:
    image: prom/node-exporter:v1.8.1
    container_name: node-exporter
    ports:
      - "9100:9100"
    volumes:
      - /:/host:ro,rslave
    command:
      - --path.rootfs=/host
      - --collector.filesystem.mount-points-exclude=^/(sys|proc|dev|host|etc)($$|/)
    restart: unless-stopped
```

> **Note** on regex: `($$|/)` uses `$$` to escape `$` for docker‑compose (prevents env var interpolation error).

Start stack:

```bash
cd /home/ubuntu/self-heal
docker-compose up -d
```

---

## 4) Prometheus config & rules

Create **/home/ubuntu/self-heal/prometheus/prometheus.yml**

```yaml
yaml
global:
  scrape_interval: 15s

rule_files:
  - "/etc/prometheus/alert.rules.yml"

# IMPORTANT: Prometheus must know where Alertmanager is (same compose network)
alerting:
  alertmanagers:
    - static_configs:
        - targets: ["alertmanager:9093"]

scrape_configs:
  - job_name: "prometheus"
    static_configs:
      - targets: ["prometheus:9090"]

  - job_name: "node"
    static_configs:
      - targets: ["node-exporter:9100"]

  - job_name: "nginx-uptime"
    metrics_path: /probe
    params:
      module: [http_2xx]
    static_configs:
      - targets:
          - http://nginx:80
    relabel_configs:
      - source_labels: [__address__]
        target_label: __param_target
      - source_labels: [__param_target]
        target_label: instance
      - target_label: __address__
        replacement: blackbox:9115
```

Create **/home/ubuntu/self-heal/prometheus/alert.rules.yml**

```yaml
yaml
groups:
  - name: self_heal_rules
    rules:
      - alert: NginxDown
        expr: probe_success{job="nginx-uptime"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "NGINX is DOWN"
          description: "Blackbox probe failed for {{ $labels.instance }}"

      - alert: HighCPU
        expr: 100 - (avg by (instance) (irate(node_cpu_seconds_total{mode="idle"}[2m])) * 100) > 90
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "High CPU on {{ $labels.instance }}"
```

Restart Prometheus after edits:

```bash
docker-compose restart prometheus
```

Open Prometheus UI: `http://<EC2_PUBLIC_IP>:9090` (Check **Status → Alerting → Alertmanagers** shows `alertmanager:9093`).

---

## 5) Alertmanager config (→ send to webhook)

Your webhook runs on the **host (EC2)** at port **5001**. Containers can reach the host by its **private IP** (e.g., `172.31.x.x`).

Create **/home/ubuntu/self-heal/alertmanager/alertmanager.yml**

```yaml
yaml
route:
  receiver: selfheal-webhook

receivers:
  - name: selfheal-webhook
    webhook_configs:
      - url: "http://<EC2_PRIVATE_IP>:5001/"
```

> Replace `<EC2_PRIVATE_IP>` with your instance private IP (the one you used in curl tests). If the EC2 IP changes, update this.

Restart Alertmanager:

```bash
docker-compose restart alertmanager
```

Open Alertmanager UI: `http://<EC2_PUBLIC_IP>:9093`

---

## 6) Webhook service (Flask on host)

Create **/home/ubuntu/self-heal/webhook.py** (same as in your canvas):

```python
python
from flask import Flask, request
import subprocess
import logging

# Log to file
logging.basicConfig(
    filename='/var/log/selfheal-webhook.log',
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)

app = Flask(__name__)

@app.route("/", methods=["POST"])
def webhook():
    data = request.json
    logging.info(f"Received alert: {data}")

    if data and "alerts" in data:
        for alert in data["alerts"]:
            if alert["status"] == "firing" and alert["labels"].get("alertname") == "NginxDown":
                logging.info("Triggering Ansible playbook to restart NGINX")
                try:
                    subprocess.run([
                        "/home/ubuntu/self-heal/run_ansible.sh"
                    ], check=True)
                    logging.info("Playbook executed successfully")
                except subprocess.CalledProcessError as e:
                    logging.error(f"Playbook execution failed: {e}")

    return "OK", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)
```

Install Flask (if not already):

```bash
pip3 install --user flask
```

Create log file and set permissions once:

```bash
sudo touch /var/log/selfheal-webhook.log
sudo chown ubuntu:ubuntu /var/log/selfheal-webhook.log
```

### systemd unit for webhook

Create **/etc/systemd/system/selfheal-webhook.service**

```ini
ini
[Unit]
Description=Self-Heal Webhook (Alertmanager receiver)
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/self-heal
ExecStart=/usr/bin/python3 /home/ubuntu/self-heal/webhook.py
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
```

Enable & start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now selfheal-webhook
sudo systemctl status selfheal-webhook --no-pager
```

Tail logs:

```bash
sudo tail -f /var/log/selfheal-webhook.log
```

> **Expected**: `405 Method Not Allowed` when you GET `/` (normal). You should see `Received alert: {...}` when alerts fire.

---

## 7) Ansible script & playbook (restart NGINX container)

Create **/home/ubuntu/self-heal/run\_ansible.sh**

```bash
bash
#!/bin/bash
# Log playbook output to a file in $HOME to avoid /var/log permissions
/usr/bin/ansible-playbook /home/ubuntu/self-heal/heal.yml >> /home/ubuntu/selfheal-ansible.log 2>&1
```

```bash
chmod +x /home/ubuntu/self-heal/run_ansible.sh
```

Create **/home/ubuntu/self-heal/heal.yml**

```yaml
yaml
- name: Restart NGINX if down
  hosts: localhost
  become: yes
  tasks:
    - name: Restart NGINX container with docker-compose
      command: /usr/bin/docker-compose -f /home/ubuntu/self-heal/docker-compose.yml restart nginx
      args:
        chdir: /home/ubuntu/self-heal/
```

> If `which docker-compose` prints a different path, update the command accordingly.

Tail Ansible run logs during tests:

```bash
tail -f /home/ubuntu/selfheal-ansible.log
```

---

## 8) Bring it all up

```bash
cd /home/ubuntu/self-heal
# Start/Restart the stack
docker-compose up -d
# Restart services after config changes
docker-compose restart prometheus alertmanager
# Ensure webhook is running
sudo systemctl restart selfheal-webhook && sudo systemctl status selfheal-webhook --no-pager
```

---

## 9) Test the full auto‑heal flow

1. **Stop NGINX container**

   ```bash
   docker-compose -f /home/ubuntu/self-heal/docker-compose.yml stop nginx
   ```
2. Wait \~30–60s → In Prometheus UI (`/alerts`) you should see **NginxDown = Firing**.
3. In Alertmanager UI you should see the same alert.
4. Webhook log should show:

   ```
   Received alert: {...}
   Triggering Ansible playbook to restart NGINX
   Playbook executed successfully
   ```
5. NGINX container auto‑restarts → alert resolves.

Manual webhook test (bypass Prometheus/AM):

```bash
curl -XPOST http://<EC2_PRIVATE_IP>:5001/ \
  -H 'Content-Type: application/json' \
  -d '{"alerts":[{"status":"firing","labels":{"alertname":"NginxDown"}}]}'
```

---

## 10) Troubleshooting Checklist

* **Prometheus doesn’t send to Alertmanager**

  * Ensure `alerting.alertmanagers.targets: ["alertmanager:9093"]` in `prometheus.yml`.
  * Prometheus UI → **/status** → *Alertmanagers* section must list one target.

* **Alert doesn’t reach webhook**

  * In `alertmanager.yml`, use EC2 **private IP** and correct port: `http://<EC2_PRIVATE_IP>:5001/`.
  * `docker logs alertmanager` to see notify errors.
  * `curl -v http://<EC2_PRIVATE_IP>:5001/` → expect **405** (webhook alive). Use POST to test.

* **Webhook receives alert but playbook doesn’t run**

  * Use absolute paths in `run_ansible.sh` and `heal.yml` (`/usr/bin/ansible-playbook`, `/usr/bin/docker-compose`).
  * Ensure `run_ansible.sh` is **executable**.
  * Log destinations writable: `/var/log/selfheal-webhook.log` (owned by ubuntu), `/home/ubuntu/selfheal-ansible.log`.
  * `journalctl -u selfheal-webhook -f` to see service errors.

* **Ansible Jinja warnings** (non‑fatal):

  * Either upgrade Ansible: `pip3 install --user "ansible-core>=2.14"`
  * Or downgrade Jinja: `pip3 install --user "jinja2<3.1"`
  * Or just ignore; playbook still runs.

* **Node exporter regex error in docker-compose**

  * Must escape `$` as `$$` in the regex: `($$|/)`.

* **Alert fires but container not restarted**

  * Confirm service name in compose is **`nginx`**: `docker-compose ps`.
  * Manually test: `docker-compose -f /home/ubuntu/self-heal/docker-compose.yml restart nginx`.

---

## 11) Deliverables (copy from this repo)

* `prometheus/prometheus.yml` ✅
* `prometheus/alert.rules.yml` ✅
* `alertmanager/alertmanager.yml` ✅
* `docker-compose.yml` ✅
* `webhook.py` ✅
* `run_ansible.sh` ✅
* `heal.yml` ✅
* **Demo logs**: `/var/log/selfheal-webhook.log`, `/home/ubuntu/selfheal-ansible.log`

---

## 12) Clean shutdown / reset

```bash
# Stop stack
cd /home/ubuntu/self-heal
docker-compose down

# Stop webhook
sudo systemctl disable --now selfheal-webhook
```

---

## 13) Optional hardening

* Restrict Alertmanager/Prometheus UIs with SG + basic auth/reverse proxy.
* Move webhook behind NGINX and bind to `127.0.0.1`.
* Use `extra_hosts` in compose to map `host.docker.internal` → host gateway so you don’t need to hardcode IP:

  ```yaml
  # under alertmanager:
  extra_hosts:
    - "host.docker.internal:host-gateway"
  # then in alertmanager.yml use:
  # url: "http://host.docker.internal:5001/"
  ```

---

You’re done 🎉  Stop the NGINX container and watch it auto‑heal!
