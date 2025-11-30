import logging
import multiprocessing

from prepare_windows import WINDOWS

DEBUG = True

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("Main")


def main() -> None:
    for window in WINDOWS:
        if DEBUG:
            logger.debug("Only starting first window in current process")
            _ = window.start_application()
        else:
            process = multiprocessing.Process(target=window.start_application, name=window.name)
            process.start()


if __name__ == "__main__":
    main()
