import logging
import multiprocessing

from .window import ReloaderWindow

logger = logging.getLogger("Main")


def start_reloaders(
    windows: list[ReloaderWindow],
    logging_level: "logging._Level" = logging.INFO,  # pyright: ignore[reportPrivateUsage]
    debug_mode: bool = False,
) -> None:
    logging.basicConfig(level=logging_level)

    if debug_mode:
        logger.debug("Only starting first window in current process")
        _ = windows[0].start_application()
    else:
        processes: list[multiprocessing.Process] = []
        for window in windows:
            process = multiprocessing.Process(target=window.start_application, name=window.name)
            process.start()
            processes.append(process)

        for process in processes:
            process.join()


if __name__ == "__main__":
    start_reloaders([])
