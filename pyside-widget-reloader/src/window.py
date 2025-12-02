import logging
import sys
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLayout, QMainWindow, QVBoxLayout, QWidget

from .module import ModuleReloader

logger = logging.getLogger("Window")


class Window:
    def __init__(
        self,
        widget: type[QWidget | QMainWindow],
        check_interval: int,
        *,
        check_sub_modules: bool = False,
        reload_sub_modules: bool = False,
        always_on_top: bool = True,
        size: tuple[int, int] | None = None,
        args: tuple[Any] | None = None,  # pyright: ignore[reportExplicitAny]
        kwargs: dict[str, Any] | None = None,  # pyright: ignore[reportExplicitAny]
        custom_qapplication: type[QApplication] | None = None,
    ) -> None:
        """Sets up a Window instance that starts application, checks files, and reload modules and widgets.

        Args:
            widget (type[QWidget | QMainWindow]): The widget class to load and reload.
            check_interval (int): Interval (in ms) to check source changes.
            check_sub_modules (bool): Whether check sub modules for changes too.
            reload_sub_modules (bool): Whether sub modules should be reloaded too.
            always_on_top (bool, optional): Whether set the window to on top. Defaults to True.
            size (tuple[int, int] | None, optional): Size of the window. Defaults to None.
            args (tuple[Any] | None, optional): args to pass to the widget. Defaults to None.
            kwargs (dict[str, Any] | None, optional): kwargs to pass to the widget. Defaults to None.
            custom_qapplication (type[QApplication] | None, optional): Custom QApplication class if needed to use overloaded QApplication.
        """
        self.widget: type[QWidget | QMainWindow] = widget
        "The widget to load."
        self.check_interval: int = check_interval
        "Interval before recheck the modules/files."
        self.check_sub_modules: bool = check_sub_modules
        "Whether check sub modules for change too."
        self.reload_sub_modules: bool = reload_sub_modules
        "Whether reload sub modules too."
        self.always_on_top: bool = always_on_top
        "Whether set the window on top."
        self.size: tuple[int, int] | None = size
        "Size of the window."
        self.args: tuple[Any] | None = args  # pyright: ignore[reportExplicitAny]
        "Arguments to pass to the widget on initialization."
        self.kwargs: dict[str, Any] | None = kwargs  # pyright: ignore[reportExplicitAny]
        "KeyWordArguments to pass to the widget on initialization."
        self.custom_qapplication: type[QApplication] | None = custom_qapplication
        "Custom QApplication object to run when starting the application."

        self._layout: QLayout
        "The layout of widget."

        self.name: str = self.widget.__name__
        "Name of the widget instance."
        self._module_path: str = self.widget.__module__
        "Path of module of widget."
        self._module_reloader: ModuleReloader = ModuleReloader.from_module_path(
            self.widget.__module__
        )
        "The Module instance of widget's module."
        self._module_reloaders: list[ModuleReloader] = [
            self._module_reloader
        ]  # TODO: custom modules to reload
        "All the modules to be reloaded."

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
        _ = timer.timeout.connect(self._check_files_and_update_widget)
        timer.start()

        QTimer.singleShot(1000, self._check_files_and_update_widget)  # TODO: should be removed

        self._update_widget()
        return app.exec()

    def _check_files_and_update_widget(self) -> None:
        reloadeds: list[bool] = []
        for module in self._module_reloaders:
            r = module.check_and_reload(self.reload_sub_modules)
            reloadeds.append(r)

        if any(reloadeds):
            self._update_widget()

    def _update_widget(self) -> None:
        # delete all the widgets in the layout
        for n in range(self._layout.count()):
            item = self._layout.itemAt(n)
            if item is None:
                continue
            _widget = item.widget()
            if _widget is None:
                continue
            _widget.deleteLater()

        # init and add new widget to the layout
        widget: type[QWidget | QMainWindow] = self._module_reloader.module.__dict__[self.name]
        args: tuple[Any, ...] = ar if (ar := self.args) else tuple()
        kwargs: dict[str, Any] = kar if (kar := self.kwargs) else dict()
        self._layout.addWidget(widget(*args, **kwargs))
