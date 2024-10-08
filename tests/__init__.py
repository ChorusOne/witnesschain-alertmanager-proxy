import os
import pathlib
import socket
import sys
import time

import requests
from fastapi.testclient import TestClient
from prometheus_client.parser import text_string_to_metric_families

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
from witnesschain_alertmanager_proxy import app

os.environ["CONFIG_FILE"] = "tests/config.yml"
client = TestClient(app)
alerts_url = "http://localhost:9093/api/v2/alerts"


def wait_for_alertmanager_port() -> None:
    max_run_time = 5
    start = time.time()
    while True:
        try:
            with socket.create_connection(("localhost", 9093)):
                break
        except OSError:
            if time.time() - start > max_run_time:
                raise RuntimeError("Backed out waiting for alertmanager port")
            time.sleep(0.1)


def test_integration() -> None:
    wait_for_alertmanager_port()
    text = (
        """
    watchtower_id: %s\nfrom: %s\ntimestamp: %s\nfile: %s\nline: %smessage: %s\n
    """
        % (
            "0x0e71247b49013664006D8472107f9e127695d9d7",
            "200",
            "Oct 7 14:26:18 2024",
            "example.go",
            "500",
            "Test alert message",
        )
    ).strip()
    response = client.post("/", json={"text": text})
    assert response.status_code == 204
    alerts = requests.get(alerts_url)
    alert_data = alerts.json()
    assert len(alert_data) > 0

    metrics_text = client.get("/metrics")
    metrics = list(text_string_to_metric_families(metrics_text.text))
    found = False
    for metric in metrics:
        if metric.name == "witnesschain_alert":
            sample = metric.samples[0]
            assert (
                sample.labels["watchtower_id"]
                == "0x0e71247b49013664006D8472107f9e127695d9d7"
            )
            assert sample.labels["file"] == "example.go"
            assert sample.labels["line"] == "500"
            found = True
    assert found
