witnesschain-alertmanager-proxy
===============================

Receive Witnesschain error webhooks and send Alertmanager alerts according to configuration.

Installation
------------
This program uses [Pipenv](https://pipenv.pypa.io/en/latest/) to manage
dependencies. It have been tested with Python 3.12

To create dedicated virtual environment and install dependencies, after
cloning an application, navigate to its root folder and invoke

```bash
pipenv sync
```

Configuration
-------------

See [config example](./config.yml.example) for the list of possible options.

Running
--------


After creating config file, run application like

```bash
pipenv run python3 witnesschain_alertmanager_proxy.py
```

By default, config file will be loaded from a location `./config.yml` in
the folder where program runs. Pass `CONFIG_FILE` environment variable to
specify alertnative location relative to working directory.
