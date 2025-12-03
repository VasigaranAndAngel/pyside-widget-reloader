import logging
import multiprocessing

from .window import Window

DEBUG = True

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("Main")


def start_reloaders(windows: list[Window]) -> None:
    for window in windows:
        if DEBUG:
            logger.debug("Only starting first window in current process")
            _ = window.start_application()
        else:
            process = multiprocessing.Process(target=window.start_application, name=window.name)
            process.start()


if __name__ == "__main__":
    start_reloaders([])
