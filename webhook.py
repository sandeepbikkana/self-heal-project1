cat > ~/self-heal/webhook.py << 'PY'
from flask import Flask, request
import subprocess, json, datetime, os

LOG = "/var/log/selfheal-webhook.log"
app = Flask(__name__)

def log(msg):
    """Write logs to a file with timestamp"""
    with open(LOG, "a") as f:
        f.write(f"{datetime.datetime.now().isoformat()} {msg}\n")

@app.route('/', methods=['POST'])
def receive():
    payload = request.get_json(force=True, silent=True) or {}
    log("Received: " + json.dumps(payload))

    alerts = payload.get("alerts", [])
    for a in alerts:
        if a.get("status") != "firing":
            continue
        name = a.get("labels", {}).get("alertname", "Unknown")
        # Run shell script that triggers ansible
        try:
            subprocess.check_call(
                ["/home/ubuntu/self-heal/run_ansible.sh", name]
            )
            log(f"Triggered Ansible for alert: {name}")
        except Exception as e:
            log(f"ERROR running Ansible for {name}: {e}")
    return "OK", 200

if __name__ == "__main__":
    os.makedirs("/var/log", exist_ok=True)
    app.run(host="0.0.0.0", port=5001)
PY
