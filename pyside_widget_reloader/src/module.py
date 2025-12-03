# TODO: need a big refactor

"""Hot-reload helpers for tracking modules and their project submodules."""

import importlib
import logging
import site
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import override

from python_minifier import minify

logger = logging.getLogger("Module")

excluded_sub_modules: list[str] = []
"Module names to be excluded when scanning for submodules."
project_dir: Path = Path(sys.argv[0]).parent

__all__ = ["excluded_sub_modules", "ModuleReloader"]


class ModuleReloader:
    """Reload modules at runtime by tracking file content hashes and optionally their submodules.

    Maintains a single ModuleReloader instance per module file path. Optionally uses a minified
    version of the source when hashing to avoid reloads due to formatting-only changes.
    """
    instances: dict[str, "ModuleReloader"] = {}
    """Contains Module instances of each module. dict[module.__file__, Module]"""
    _check_locked: bool = False

    def __new__(
        cls, module: ModuleType, ruff_check: bool = False, minify_source: bool = False
    ) -> "ModuleReloader":
        """Create or return the unique reloader instance for a module.

        Ensures a single instance per module file path. Subsequent constructions
        return the existing instance.

        Args:
            module: Module object to manage and reload.
            ruff_check: If True, indicates Ruff should gate reloads (currently always run).
            minify_source: If True, hash a minified version of the source to reduce
                reloads caused by formatting-only changes.

        Returns:
            ModuleReloader: The reloader bound to the module's file.

        Raises:
            Exception: If the module has no __file__ attribute.
        """
        if module.__file__ is None:
            raise Exception(f"Attribute __file__ of Module: {module} is None.")

        # return the existing module if an instance is already initialized for this module.
        if module.__file__ in ModuleReloader.instances:
            return ModuleReloader.instances[module.__file__]
        else:
            logger.debug(f"Initializing ModuleReloader for module: {module.__name__}")
            self = super().__new__(cls)
            ModuleReloader.instances[module.__file__] = self
            self.module = module
            self.ruff_check = ruff_check
            self.minify_source = minify_source
            self._file_hash = self._get_hash()
            self._sub_modules = self._get_sub_modules()
            self._is_changed_ = None
            self._is_reloaded_ = None
            return self

    def __init__(
        self, module: ModuleType, ruff_check: bool = False, minify_source: bool = False
    ) -> None:
        """No-op initializer; attributes are set in __new__.

        This method exists to provide type annotations for static analysis.
        """
        self.module: ModuleType
        self.ruff_check: bool
        self.minify_source: bool
        self._file_hash: int
        self._sub_modules: set[ModuleReloader]
        self._is_changed_: bool | None
        """Whether the module is changed or not. None if not checked."""
        self._is_reloaded_: bool | None
        """Whether the module is reloaded. None if not checked."""

    def _get_hash(self) -> int:
        """Compute a hash of the module's source file.

        Attempts text read first; when minify_source is enabled and text read succeeds,
        hashes the minified source to avoid spurious reloads from formatting-only edits.

        Returns:
            int: Hash of the current file contents.

        Raises:
            Exception: If the module lacks a __file__ attribute.
        """
        if self.module.__file__ is None:
            raise Exception(f"Module: {self.module} doesn't have __file__ attribute.")

        path = Path(self.module.__file__)

        # try reading and minifying the source code
        try:
            source_code = path.read_text()
        except Exception:
            source_content = path.read_bytes()
        else:  # if success reading text
            if self.minify_source:
                try:
                    source_content = minify(source_code, path.as_posix())
                except Exception:
                    source_content = source_code
            else:
                source_content = source_code

        return hash(source_content)

    def _reload(self) -> None:
        """Reload the module and refresh its discovered submodules."""
        logger.info(f"Reloading module: {self.module.__name__}")
        self.module = importlib.reload(self.module)
        self._sub_modules = self._get_sub_modules()

    def check_and_reload(
        self, check_sub_modules: bool = True, reload_sub_modules: bool = True
    ) -> bool:
        """Check for changes and reload the module (and optionally submodules).

        Wraps the internal check with a lock to avoid duplicated work across instances.

        Args:
            check_sub_modules: Include submodules in change detection.
            reload_sub_modules: Reload submodules first, then this module if needed.

        Returns:
            bool: True if this module reloaded during the call.
        """
        self._lock_check()
        ret = self._check_and_reload(check_sub_modules, reload_sub_modules)
        self._unlock_check()
        return ret

    def _check_and_reload(
        self, check_sub_modules: bool = True, reload_sub_modules: bool = True
    ) -> bool:
        """Reload the module if its hash changed (including submodules when enabled).

        Ruff is executed as a guard; reloading happens only when it reports no errors.

        Args:
            check_sub_modules: Whether to include submodules in change detection.
            reload_sub_modules: Whether to reload submodules first, then this module.

        Returns:
            bool: True if the module was reloaded.
        """
        if self._is_reloaded_ is not None:
            return self._is_reloaded_

        reloaded = False
        self._is_reloaded_ = False
        if self._is_changed(check_sub_modules):
            ruff_process = subprocess.run(
                f"ruff check {self.module.__file__}", stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )  # TODO: ruff check should only run on python source files
            if ruff_process.returncode:
                logging.debug(f"Found error on `ruff check {self.module.__file__}`. Not reloading.")
            else:
                # TODO: reload only if any of imports changed
                self._reload()
                reloaded = True
                self._is_reloaded_ = True

        if reload_sub_modules:
            _reloadeds: list[bool] = []
            for module in self._sub_modules:
                _reloaded = module._check_and_reload(check_sub_modules, reload_sub_modules)
                _reloadeds.append(_reloaded)
            # Reload again after sub modules are reloaded.
            if any(_reloadeds):
                self._reload()
                reloaded = True

        if reloaded:
            self._file_hash = self._get_hash()

        self._unlock_check()
        return reloaded

    def _is_changed(self, check_sub_modules: bool = False) -> bool:
        """Return True if this module's hash (or any submodule when enabled) changed.

        Uses cached state while checks are locked to avoid recomputation.

        Args:
            check_sub_modules: Include submodules in the change detection.

        Returns:
            bool: True if a change is detected.
        """
        if ModuleReloader._check_locked and self._is_changed_ is not None:
            return self._is_changed_

        changeds: list[bool] = []
        changeds.append(self._file_hash != self._get_hash())
        self._is_changed_ = any(changeds)

        if check_sub_modules:
            for module in self._sub_modules:
                changeds.append(module._is_changed(check_sub_modules))

        changed = any(changeds)
        self._is_changed_ = changed

        return changed

    def _get_sub_modules(self) -> set["ModuleReloader"]:
        """Discover project submodules referenced by this module.

        Scans the module namespace for imported modules that:
        - live under the project directory,
        - are Python source files,
        - are not under site-packages,
        - are not in the excluded_sub_modules list.

        Returns:
            set[ModuleReloader]: Reloaders for discovered submodules.
        """
        site_package_paths = list(map(Path, site.getsitepackages()))
        sub_modules: set["ModuleReloader"] = set()
        for i in self.module.__dict__.values():
            # TODO: filter out buil-ins and other built-in modules.
            # TODO: currently not able to get submodules if only variable imported.
            # TODO: get __init__.py files too
            # region check if the module file is one of project files.
            module_name: str | None = getattr(i, "__module__", None)
            if module_name is None:
                continue
            if module_name in excluded_sub_modules:
                continue
            module = sys.modules.get(module_name, None)
            if module is None or module is self.module:
                continue
            module_file: str | None = getattr(module, "__file__", None)
            if module_file is None:
                continue
            if not module_file.lower().endswith(".py"):
                continue
            module_path = Path(module_file)
            if project_dir not in module_path.parents:
                continue
            _continue: bool = False
            for spp in site_package_paths:
                if spp in module_path.parents:
                    _continue = True
                    break
            if _continue:
                continue
            # endregion
            sub_modules.add(ModuleReloader(module, self.ruff_check, self.minify_source))

        return sub_modules

    @override
    def __repr__(self) -> str:
        return f'<ModuleReloader for "{self.module.__name__}" module.'

    @override
    def __str__(self) -> str:
        return self.__repr__()

    @staticmethod
    def _lock_check() -> None:
        """Enable a cross-instance lock to reuse cached change checks."""
        ModuleReloader._check_locked = True

    @staticmethod
    def _unlock_check() -> None:
        """Release the check lock and reset per-instance cached flags."""
        ModuleReloader._check_locked = False
        for ins in ModuleReloader.instances.values():
            ins._is_changed_ = None
            ins._is_reloaded_ = None

    @staticmethod
    def from_module_path(path: str) -> "ModuleReloader":
        """Get a Module instance from module path (eg: `sys`, `parent.module`)

        Gets a Module instance from module path if exists in sys.modules. else tries to import the
        module.

        Args:
            path (str): path of module (eg: `sys`, `parent`)

        Returns:
            Module: Instance of Module
        """
        if path not in sys.modules.keys():
            sys.modules[path] = importlib.import_module(path)
        return ModuleReloader(sys.modules[path])
