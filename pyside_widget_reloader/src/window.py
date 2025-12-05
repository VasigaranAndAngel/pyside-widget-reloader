import logging
import sys
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLayout, QMainWindow, QVBoxLayout, QWidget

from .module import ModuleReloader

logger = logging.getLogger("Window")


class Window:
    """Host window that hot-reloads and displays a target Qt widget.

    Manages a QTimer to watch Python modules for changes and rebuilds the
    target widget in-place when a reload occurs.
    """

    def __init__(
        self,
        widget: type[QWidget | QMainWindow],
        check_interval: int,
        *,
        check_sub_modules: bool = False,
        reload_sub_modules: bool = False,
        ruff_check: bool = False,
        minify_source: bool = False,
        always_on_top: bool = True,
        size: tuple[int, int] | None = None,
        args: tuple[Any] | None = None,  # pyright: ignore[reportExplicitAny]
        kwargs: dict[str, Any] | None = None,  # pyright: ignore[reportExplicitAny]
        custom_qapplication: type[QApplication] | None = None,
    ) -> None:
        """Initialize the hot-reload host window.

        Prepares configuration for the reload loop and optional custom QApplication.
        This does not start the Qt event loop; call start_application() to run the app.

        Args:
            widget (type[QWidget | QMainWindow]): Qt widget class to instantiate and reload on changes.
            check_interval (int): Interval in milliseconds to poll for file changes.
            check_sub_modules (bool, optional): Whether to also watch submodules of the widget's module. Defaults to False.
            reload_sub_modules (bool, optional): Whether to reload submodules when a change is detected. Defaults to False.
            ruff_check (bool, optional): Whether to run ruff before reloading a module. Defaults to False.
            minify_source (bool, optional): Whether to minify the source before reloading a module. Defaults to False.
            always_on_top (bool, optional): Whether the host window should stay on top. Defaults to True.
            size (tuple[int, int] | None, optional): Optional initial window size as (width, height). Defaults to None.
            args (tuple[Any] | None, optional): Positional arguments passed to the widget constructor. Defaults to None.
            kwargs (dict[str, Any] | None, optional): Keyword arguments passed to the widget constructor. Defaults to None.
            custom_qapplication (type[QApplication] | None, optional): Custom QApplication subclass to use instead of the default.
        """
        # NOTE: When launching the UI in a separate process, this instance is pickled
        # and sent to the child. Therefore, all attributes created in __init__() must be
        # fully picklable. Do NOT store unpicklable state here. Such objects should be created
        # inside start_application() or any methods executed in the child process.

        self.widget: type[QWidget | QMainWindow] = widget
        "The widget to load."
        self.check_interval: int = check_interval
        "Interval before recheck the modules/files."
        self.check_sub_modules: bool = check_sub_modules
        "Whether check sub modules for change too."
        self.reload_sub_modules: bool = reload_sub_modules
        "Whether reload sub modules too."
        self.ruff_check: bool = ruff_check
        "Whether run ruff check before reloading."
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
        self._module_reloader: ModuleReloader
        "The Module instance of widget's module."
        self._module_reloaders: list[ModuleReloader]
        "All the modules to be reloaded."

    def start_application(self) -> int:
        """Start a minimal Qt application and begin periodic reload checks.

        Sets up a top-level QWidget and layout container, schedules a timer to
        periodically check watched modules for changes, and rebuilds the
        displayed widget when a reload occurs.

        Returns:
            int: The Qt application exit code.
        """
        # NOTE: This method executes in a separate child process.

        self._module_reloader = ModuleReloader.from_module_path(self.widget.__module__)
        self._module_reloaders = [self._module_reloader]  # TODO: custom modules to reload

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

        self._update_widget()
        return app.exec()

    def _check_files_and_update_widget(self) -> None:
        """Check watched modules and update the UI if any module reloads."""
        reloadeds: list[bool] = []
        for module in self._module_reloaders:
            r = module.check_and_reload(self.check_sub_modules, self.reload_sub_modules)
            reloadeds.append(r)

        if any(reloadeds):
            self._update_widget()

    def _update_widget(self) -> None:
        """Recreate the target widget using the latest reloaded module.

        Removes any existing widget instances from the layout, imports the
        current class from the module reloader, and instantiates it with the
        configured args/kwargs.
        """
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
        widget = self._module_reloader.module.__dict__[self.name]  # pyright:ignore[reportAny]
        if not isinstance(widget, type):
            raise ValueError(
                f"Widget {self.name} is not a QWidget or QMainWindow.",
                "If the widget is renamed or moved, please update and restart the application.",
            )
        if not issubclass(widget, (QWidget, QMainWindow)):
            raise ValueError(
                f"Widget {self.name} is not a QWidget or QMainWindow.",
                "If the widget is renamed or moved, please update and restart the application.",
            )
        args: tuple[Any, ...] = ar if (ar := self.args) else tuple()  # pyright:ignore[reportExplicitAny]
        kwargs: dict[str, Any] = kar if (kar := self.kwargs) else dict()  # pyright:ignore[reportExplicitAny]
        self._layout.addWidget(widget(*args, **kwargs))  # pyright:ignore[reportAny]
