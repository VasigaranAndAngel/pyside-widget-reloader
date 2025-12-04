# TODO: need a big refactor

"""Module Reloader for Hot-Reloading Python Modules.

This module provides the `ModuleReloader` class, a utility designed for hot-reloading
Python modules during development. It tracks changes in source files by hashing their
content and supports recursively checking and reloading project-local submodules.

Key Features:
- Reloads modules only when their source code (or the source of their dependencies) changes.
- Optionally minifies source code before hashing to ignore formatting-only changes.
- Discovers and reloads submodules within the same project.
- Avoids redundant checks using a global lock during a reload cycle.
- Integrates with Ruff to gate reloads on successful linting checks.

Usage:
    reloader = ModuleReloader(my_module)
    reloader.check_and_reload()
"""

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
"""The root directory of the project, used to identify project-local modules."""

__all__ = ["excluded_sub_modules", "ModuleReloader"]


class ModuleReloader:
    """Reload modules at runtime by tracking file content hashes and optionally their submodules.

    Maintains a single ModuleReloader instance per module file path. Optionally uses a minified
    version of the source when hashing to avoid reloads due to formatting-only changes.
    """

    instances: dict[str, "ModuleReloader"] = {}
    """Contains Module instances of each module. dict[module.__file__, Module]"""
    _check_locked: bool = False
    """A global lock to prevent redundant change checks within a single reload cycle."""

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
            self._parent_modules = self._get_parent_modules()
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
        """The module being managed."""
        self.ruff_check: bool
        """If True, Ruff will be used to check for errors before reloading."""
        self.minify_source: bool
        """If True, the source is minified before hashing to ignore formatting changes."""
        self._file_hash: int
        """The hash of the module's source file, used for change detection."""
        self._sub_modules: set[ModuleReloader]
        """A set of reloaders for modules imported by this one."""
        self._parent_modules: list[ModuleReloader]
        """A list of reloaders for parent modules."""
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
        """Reload the module, refresh submodules, and trigger parent reloads.

        After reloading the current module, it re-scans for submodules and parent
        modules. It then recursively calls `_reload` on each parent to propagate
        the change up the import chain, ensuring that modules importing this one
        receive the updated version.
        """
        logger.info(f"Reloading module: {self.module.__name__}")
        self.module = importlib.reload(self.module)
        self._sub_modules = self._get_sub_modules()
        self._parent_modules = self._get_parent_modules()
        for parent in self._parent_modules:
            parent._reload()

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
        """Internal logic to reload the module if changed.

        Checks for source code changes and, if detected, runs `ruff check` as a guard.
        Reloading proceeds only if Ruff reports no errors. It can also trigger reloads
        for submodules.

        Note:
            The Ruff check is currently applied to all file types, but should be
            restricted to Python source files.

        Args:
            check_sub_modules: If True, include submodules in the change detection.
            reload_sub_modules: If True, reload submodules before this module.

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
        """Check if the module or its dependencies have changed.

        Compares the current file hash with its stored hash. If `check_sub_modules`
        is True, it recursively checks for changes in all discovered submodules.
        The check also propagates up to parent modules to ensure that importers
        are reloaded correctly.

        Uses a cached state (`_is_changed_`) during a locked check cycle to avoid
        redundant computations and prevent circular dependencies.

        Args:
            check_sub_modules: If True, recursively check submodules for changes.

        Returns:
            bool: True if a change is detected in this module or its dependencies.
        """
        # logger.info(f'Checking if "{self.module.__name__}" changed.')
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

        if not changed:
            for parent in self._parent_modules:
                changeds.append(parent._is_changed(check_sub_modules=False))

            changed = any(changeds)
            self._is_changed_ = changed

        return changed

    def _get_sub_modules(self) -> set["ModuleReloader"]:
        """Discover and return project-local submodules.

        Scans the module's `__dict__` for imported modules and filters them to
        identify project-local submodules.

        A module is considered a project submodule if it:
        - Is located within the project's root directory (`project_dir`).
        - Is a Python source file (ends with `.py`).
        - Is not part of a `site-packages` directory.
        - Is not in the `excluded_sub_modules` list.

        Note:
            This discovery has limitations:
            - It may not detect built-in or standard library modules correctly.
            - It cannot find submodules when only a variable or function is imported
              (e.g., `from my_module import my_variable`).
            - It does not currently handle `__init__.py` files explicitly.

        Returns:
            set[ModuleReloader]: A set of `ModuleReloader` instances for the
            discovered submodules.
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

    def _get_parent_modules(self) -> list["ModuleReloader"]:
        """Identify and return all parent modules in the hierarchy.

        For a module named `a.b.c`, its parents are `a.b` and `a`. This method
        finds all existing parent modules and returns a list of `ModuleReloader`
        instances for them.

        Returns:
            list[ModuleReloader]: A list of reloaders for parent modules, ordered
            from the immediate parent to the top-level ancestor.
        """
        module_name = self.module.__name__
        if "." in module_name:
            parent_parts = module_name.split(".")[:-1]
            parents: list[ModuleReloader] = []
            for i in range(len(parent_parts)):
                module_name = ".".join(parent_parts[: i + 1])
                module = sys.modules.get(module_name, None)
                if (
                    module is not None
                    and module.__file__ is not None
                    and Path(module.__file__).exists()
                ):
                    parents.append(
                        ModuleReloader(
                            module, ruff_check=self.ruff_check, minify_source=self.minify_source
                        )
                    )
            return list(reversed(parents))
        return list()

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
    def from_module_path(
        path: str, ruff_check: bool = False, minify_source: bool = False
    ) -> "ModuleReloader":
        """Create or retrieve a ModuleReloader from a module path string.

        If the module is not already in `sys.modules`, it will be imported.
        This serves as a factory function to get a reloader instance without
        having the module object beforehand.

        Args:
            path: The dot-separated path of the module (e.g., `my_package.my_module`).
            ruff_check: If True, indicates Ruff should gate reloads.
            minify_source: If True, hash a minified version of the source.

        Returns:
            ModuleReloader: An instance of the reloader for the specified module.
        """
        if path not in sys.modules.keys():
            sys.modules[path] = importlib.import_module(path)
        return ModuleReloader(sys.modules[path], ruff_check=ruff_check, minify_source=minify_source)
