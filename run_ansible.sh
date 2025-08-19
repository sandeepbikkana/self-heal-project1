cat > ~/self-heal/run_ansible.sh << 'SH'
#!/usr/bin/env bash
set -e
ALERTNAME="$1"
LOG="/var/log/selfheal-runner.log"
echo "$(date -Is) Running Ansible for alert: ${ALERTNAME}" | tee -a "$LOG"
ansible-playbook /home/ubuntu/self-heal/heal.yml --extra-vars "alertname=${ALERTNAME}" | tee -a "$LOG"
SH
chmod +x ~/self-heal/run_ansible.sh
