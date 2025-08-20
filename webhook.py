from flask import Flask, request
import subprocess
import logging

# Setup logging
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
                    subprocess.run(
                        ["/home/ubuntu/self-heal/run_ansible.sh"],
                        check=True
                    )
                    logging.info("Playbook executed successfully")
                except subprocess.CalledProcessError as e:
                    logging.error(f"Playbook execution failed: {e}")

    return "OK", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)

