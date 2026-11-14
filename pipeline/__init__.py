"""The Rebellion of the Machines — data pipeline.

Pulls real public threat intelligence, geolocates it, reskins it as a daily
"machine uprising" (Insurgency Report), and emits JSON + binary snapshots that
the 3D globe frontend consumes. Runs both as an AWS Lambda and as a local CLI.
"""

__version__ = "1.0.0"
