"""Start Viewdesk: the automation (app.py) and its UI (ui.py) together."""
import sys

sys.dont_write_bytecode = True  # keep the workspace free of __pycache__

import ui
from app import Automation


def main():
    automation = Automation()
    automation.start_bootstrap()  # signs in automatically with the saved account
    ui.serve(automation, open_window="--no-window" not in sys.argv)


if __name__ == "__main__":
    main()
