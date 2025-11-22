from contextlib import suppress
import importlib
import multiprocessing
import os
import sys
from collections.abc import Sequence
from functools import partial
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLayout, QVBoxLayout, QWidget

sys.path.insert(0, os.path.abspath("../tagstudio"))

APPLICATION_PATH: str = os.path.abspath(os.path.join(os.path.split(__file__)[0], "..", "tagstudio"))
AP = APPLICATION_PATH

DEBUG = False


def debug(*message: str) -> None:
    if DEBUG:
        print("UITest: ", *message)  # noqa: T201


class Window:
    def __init__(
        self,
        widget: type,
        files_to_check: Sequence[str],
        check_interval: int,
        *,
        always_on_top: bool = True,
        size: tuple[int, int] | None = None,
        args: tuple[Any] | None = None,  # pyright: ignore[reportExplicitAny]
        kwargs: dict[str, Any] | None = None,  # pyright: ignore[reportExplicitAny]
        custom_qapplication: type[QApplication] | None = None,
    ) -> None:
        self.widget: type = widget
        self.files_to_check: list[str] = list(os.path.abspath(file) for file in files_to_check)
        self.check_interval: int = check_interval
        self.always_on_top: bool = always_on_top
        self.size: tuple[int, int] | None = size
        self.args: tuple[Any] | None = args  # pyright: ignore[reportExplicitAny]
        self.kwargs: dict[str, Any] | None = kwargs  # pyright: ignore[reportExplicitAny]
        self.custom_qapplication: type[QApplication] | None = custom_qapplication

        self._layout: QLayout

        self._module: object | None = None

        self.name: str = self.widget.__name__
        self.module_path: str = self.widget.__module__

        for i in range(len(self.files_to_check)):
            file = self.files_to_check[i]
            abs_path = os.path.abspath(file)
            assert os.path.isfile(abs_path), f"File {abs_path} does not exist"
            self.files_to_check[i] = abs_path

        self._file_hashes: list[int] = [0] * len(self.files_to_check)

    def start_application(self) -> int:
        ar = sys.argv
        app = QApplication(ar) if self.custom_qapplication is None else self.custom_qapplication(ar)
        window = QWidget()
        window.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, self.always_on_top)
        window.show()
        if self.size is not None:
            window.setGeometry(window.pos().x(), window.pos().y(), self.size[0], self.size[1])

        window.setLayout(vlayout := QVBoxLayout())
        vlayout.addLayout(hlayout := QHBoxLayout())

        self._layout = hlayout

        timer = QTimer(window)
        timer.setInterval(self.check_interval)
        _ = timer.timeout.connect(partial(self._check_files_and_update_widget, hlayout, window))
        timer.start()

        return app.exec()

    def _check_files_and_update_widget(self, layout: QLayout, parent: QWidget) -> None:
        reloaded: bool = False
        for file, old_hash in zip(self.files_to_check, self._file_hashes):
            # if not Path(file).exists():
            #     raise FileNotFoundError(f"File {file} does not exist")
            with open(file) as f:
                new_hash = hash(f.read())
            if new_hash != old_hash:
                if not reloaded:
                    with suppress():
                        self._update_module()
                        self._update_widget()
                        reloaded = True

                # update new hash
                self._file_hashes[self.files_to_check.index(file)] = new_hash

    def _update_module(self) -> None:
        if self._module is None:
            self._module = importlib.import_module(self.module_path)  # type: ignore
        else:
            # reload all submodules
            submodule_names: set[str] = set()

            for item in self._module.__dict__.values():
                if isinstance(item, type):
                    submodule_names.add(item.__module__)

            path_to_module = {}
            "Module path to module map"

            for module_name in submodule_names:
                module = sys.modules[module_name]
                path_to_module[str(Path(module.__file__ or "")).lower()] = module
                # module = sys.modules[module_name]
                # module_path = os.path.abspath(module.__file__ or "").lower()
                # if module_path in (path.lower() for path in self.files_to_check):
                #     modules_to_reload.append(module)

            modules_to_reload = []

            for file in (path.lower() for path in self.files_to_check):
                if file in path_to_module:
                    modules_to_reload.append(path_to_module[file])

            modules_to_reload.append(self._module)

            # reload main module
            for module in modules_to_reload:
                debug("Reloading module:", module.__name__)
                _ = importlib.reload(module)

    def _update_widget(self) -> None:
        # delete all the widgets in the layout
        for n in range(self._layout.count()):
            item = self._layout.itemAt(n)
            if item is None:
                continue
            _widget = item.widget()
            if _widget is None:  # pyright: ignore[reportUnnecessaryComparison] coz, item.widget() would return None
                continue
            _widget.deleteLater()

        # add new widget to the layout
        if self._module is not None:
            widget = self._module.__dict__[self.name]
            args = ar if (ar := self.args) else tuple()
            kwargs = kar if (kar := self.kwargs) else dict()
            self._layout.addWidget(widget(*args, **kwargs))


def prepare_windows() -> list[Window]:
    windows: list[Window] = []



    return windows


def main() -> None:
    windows = prepare_windows()
    for window in windows:
        if DEBUG:
            debug("Only starting first window in current process")
            _ = window.start_application()
        else:
            process = multiprocessing.Process(target=window.start_application, name=window.name)
            process.start()


if __name__ == "__main__":
    main()
