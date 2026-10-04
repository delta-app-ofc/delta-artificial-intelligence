"""Evita que a suíte leia o .env local da máquina desenvolvedora."""

import os

os.environ["APP_ENV"] = "test"
