"""The Rebellion of the Machines — data pipeline.

Pulls real cyberattacks reported by recognized news outlets (BBC, The Washington
Post, The New York Times, The Hacker News, HackerNoon), extracts where/what/how-bad/how-to-
prevent, reskins them as a weekly "machine uprising" (Insurgency Report), and emits
JSON + binary snapshots that the 3D globe frontend consumes. Runs both as an AWS
Lambda and as a local CLI.
"""

__version__ = "2.0.0"
