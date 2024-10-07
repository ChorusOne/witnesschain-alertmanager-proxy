from datetime import datetime, timedelta
import functools
import logging
import os
import pathlib
import string
import sys
import typing

from fastapi import Depends, FastAPI, Response
import furl  # type: ignore[import-untyped]
from prometheus_client import Gauge, make_asgi_app
from pydantic import AfterValidator, BaseModel, ConfigDict
from pydantic_settings import BaseSettings
import requests
import yaml


logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s.%(msecs)03d %(levelname)s %(module)s - %(funcName)s: %(message)s",
)
logger = logging.getLogger(__name__)


app = FastAPI()
witnesschain_alert = Gauge(
    name="witnesschain_alert",
    documentation="Witnesschain alert count",
    labelnames=["file", "line", "watchtower_id"],
)


StringTemplate = typing.Annotated[str, AfterValidator(string.Template)]
AlertMangerUrl = typing.Annotated[str, AfterValidator(furl.furl)]


class WitnessChainErrorLog(BaseModel):
    """An alert message as received from Witness Chain."""

    text: str


class Alert(BaseModel):
    """An internal alert representation."""

    labels: typing.Dict[str, str] = {}

    # Computed properties
    description: str | None = None
    summary: str | None = None
    generator_url: str | None = None

    @classmethod
    def from_incoming_text(cls, text: str) -> typing.Self:
        """
        Parses following incoming message from Witnesschain and sends alert

        message := fmt.Sprintf("watchtower_id: %v\nfrom: %v\ntimestamp: %v\nfile: %v\nline: %vmessage: %v\n", simpleConfig.WatchtowerAddress, from, now, file, line, fatalErrorMessageString)

        request, _ := json.Marshal(map[string] interface{}{
            "text": message,
        })

        requestBody := bytes.NewBuffer(request)
        """
        text, msg = text.strip().split("message:")
        input_label_lines = text.strip().split("\n")
        labels = {}
        labels["message"] = msg
        for input_label in input_label_lines:
            name, value = input_label.split(":", 1)
            value = value.strip()
            labels[name] = value
        alert = cls(labels=labels)
        return alert


class AlertManagerConfig(BaseModel):
    """Configuration for alertmanager access."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    url: AlertMangerUrl
    timeout_ms: int = 30000

    @functools.cached_property
    def session(self) -> requests.Session:
        sess = requests.Session()
        setattr(
            sess,
            "request",
            functools.partial(sess.request, timeout=self.timeout_ms / 1000.0),
        )
        sess.headers = {
            "Content-Type": "application/json",
            "User-Agent": "witnesschain_alertmanager_proxy.py",
        }
        return sess

    def send_alert(self, name: str, duration_ms: int, alert: Alert) -> None:
        alert.labels["alertname"] = name
        alertmanager_inputs = {
            "status": "firing",
            "labels": alert.labels,
            "annotations": {
                "description": alert.description,
                "summary": alert.summary,
            },
            "endsAt": (
                datetime.utcnow() + timedelta(milliseconds=duration_ms)
            ).isoformat(),
        }
        if alert.generator_url is not None:
            alertmanager_inputs["generatorURL"] = alert.generator_url
        try:
            response = self.session.post(str(self.url), json=[alertmanager_inputs])
        except (requests.RequestException, OSError):
            logger.exception("Failed to send alert %s to alertmanager: %r", alert)
            logger.critical("Alert processing fails")
            raise RuntimeError("Failed to send alert")
        else:
            if response.status_code != 200:
                logger.critical(
                    "Failed to send alert into alert manager, status=%s",
                    response.status_code,
                )
                logger.error("Alertmanager error message: %s", response.content)
                raise RuntimeError("Failed to send alert")
            logger.info("Successfully sent alert %s to alertmanager", alert)


class AlertConfig(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    duration_ms: int
    description_tpl: StringTemplate = string.Template(
        """
Witnesschain FATAL failure for ${WATCHTOWER_ID}
        """
    )  # type: ignore[assignment]
    summary_tpl: StringTemplate = string.Template(
        """
Received FATAL alert from Witnesschain Watchtower with address=${WATCHTOWER_ID},
process of signing witness proofs might be interrupted. Watchtower message:
${MESSAGE}
    """
    )  # type: ignore[assignment]
    generator_url_tpl: StringTemplate = string.Template(
        "https://explorer.witnesschain.com/address/${WATCHTOWER_ID}"
    )  # type: ignore[assignment]

    # These value are NOT shared mutable: https://stackoverflow.com/a/73621352
    label_remove: typing.List[str] = ["line", "file", "timestamp"]
    label_append: typing.Dict[str, str] = {}

    # Optional internal error to send
    internal_error: Alert | None = None

    def render(self, alert: Alert) -> Alert:
        for label in self.label_remove:
            if label in alert.labels:
                del alert.labels[label]
                logger.info("Removed label %s from alert", label)
        for label, value in self.label_append.items():
            alert.labels[label] = value

        render_ctx = {}
        for label, value in alert.labels.items():
            render_ctx[label.upper()] = value

        alert.summary = self.summary_tpl.substitute(**render_ctx).strip()  # type: ignore[attr-defined]
        alert.description = self.description_tpl.substitute(**render_ctx).strip()  # type: ignore[attr-defined]

        # Generator URL is optional
        generator_url = self.generator_url_tpl.substitute(**render_ctx).strip()  # type: ignore[attr-defined]
        if generator_url:
            alert.generator_url = generator_url

        return alert

    def on_internal_error(self, exc: BaseException) -> Alert | None:
        alert = self.internal_error
        if alert is not None:
            exc_msg = str(exc)
            alert.labels["message"] = exc_msg
        return alert


class ProcessingConfig(BaseModel):
    alert: AlertConfig
    manager: AlertManagerConfig

    def send_alert(self, alert: Alert) -> None:
        self.manager.send_alert(self.alert.name, self.alert.duration_ms, alert=alert)

    def send_internal_alert(self, exc: BaseException) -> None:
        alert = self.alert.on_internal_error(exc)
        if alert is not None:
            self.manager.send_alert(
                "WitnessChainErrorProxyInternalAlert",
                self.alert.duration_ms,
                alert=alert,
            )


class WitnesschainAlertmanagerProxy(BaseSettings):

    config: ProcessingConfig

    def render(self, alert: Alert) -> Alert:
        return self.config.alert.render(alert)

    def send_alert(self, alert: Alert) -> None:
        self.config.send_alert(alert)

    def incoming(self, fatal: WitnessChainErrorLog) -> Alert:
        return Alert.from_incoming_text(fatal.text)


@functools.lru_cache
def get_proxy_config() -> WitnesschainAlertmanagerProxy:
    config_path = os.environ.get("CONFIG_FILE", "config.yml")
    config_yaml_path = pathlib.Path(__file__).parent / config_path
    if not config_yaml_path.exists():
        logger.error("YAML config file not found at %s", config_yaml_path)
        exit(2)
    config_data = yaml.safe_load(config_yaml_path.read_text())
    proxy = WitnesschainAlertmanagerProxy(**config_data)
    return proxy


ProxySettings = typing.Annotated[
    WitnesschainAlertmanagerProxy, Depends(get_proxy_config)
]


@app.post("/")
def alert(proxy: ProxySettings, body: WitnessChainErrorLog, response: Response) -> str:
    """Receive Witnesschain alert, transform into Alertmanager alert, send to Alertmanager."""
    try:
        logger.info("Received witnesschain error log: %s", body)
        assert (
            body.text
        ), "Text received from WitnessChain Watchtower should not be empty"
        alert = proxy.incoming(body)
        ts = datetime.strptime(alert.labels["timestamp"], "%b %d %H:%M:%S %Y")
        witnesschain_alert.labels(
            alert.labels["file"], alert.labels["line"], alert.labels["watchtower_id"]
        ).set(ts.timestamp())
        rendered = proxy.render(alert)
        proxy.send_alert(rendered)
        response.status_code = 204
        return ""
    except Exception as exc:
        logger.exception(
            "Failed processing incoming data, sending internal alert for exception"
        )
        response.status_code = 500
        proxy.config.send_internal_alert(exc)
        return str(exc)


@app.get("/health")
def health() -> str:
    return "OK"


metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)
