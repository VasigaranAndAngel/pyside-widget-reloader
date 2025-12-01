# TODO: need a big refactor

import importlib
import logging
import site
import subprocess
import sys
from pathlib import Path
from types import ModuleType

from python_minifier import minify

logger = logging.getLogger("Module")

excluded_sub_modules: list[str] = []
"Module names to be excluded when scanning for submodules."

__all__ = ["excluded_sub_modules", "ModuleReloader"]


class ModuleReloader:
    instances: dict[str, "ModuleReloader"] = {}
    """Contains Module instances of each module. dict[module.__file__, Module]"""
    _check_locked: bool = False

    def __new__(cls, module: ModuleType) -> "ModuleReloader":
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
            self._file_hash = self._get_hash()
            self._sub_modules = self._get_sub_modules()
            self._is_changed_ = None
            self._is_reloaded_ = None
            return self

    def __init__(self, module: ModuleType) -> None:
        self.module: ModuleType
        self._file_hash: int
        self._sub_modules: set[ModuleReloader]
        self._is_changed_: bool | None
        """Whether the module is changed or not. None if not checked."""
        self._is_reloaded_: bool | None
        """Whether the module is reloaded. None if not checked."""

    def _get_hash(self) -> int:
        if self.module.__file__ is None:
            raise Exception(f"Module: {self.module} doesn't have __file__ attribute.")

        path = Path(self.module.__file__)

        # try reading and minifying the source code
        try:
            source_code = path.read_text()
        except Exception:
            source_content = path.read_bytes()
        else:  # if success reading text
            try:
                source_content = minify(source_code, path.as_posix())
            except Exception:
                source_content = source_code

        return hash(source_content)

    def _reload(self) -> None:
        logger.info(f"Reloading module: {self.module}")
        self.module = importlib.reload(self.module)
        self._sub_modules = self._get_sub_modules()

    def check_and_reload(
        self, check_sub_modules: bool = True, reload_sub_modules: bool = True
    ) -> bool:
        self._lock_check()
        ret = self._check_and_reload(check_sub_modules, reload_sub_modules)
        self._unlock_check()
        return ret

    def _check_and_reload(
        self, check_sub_modules: bool = True, reload_sub_modules: bool = True
    ) -> bool:
        """Reloades the module if the hash isn't the same. Returns True if reloaded."""
        logger.debug(f"checking_and_reload in {self.module}; {self._is_reloaded_=}")
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
        logging.debug(f"_is_changed in {self.module}; {self._is_changed_=}")
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

        logger.info(f"Checking if changed: {self.module}; {check_sub_modules=}:: {changed}")
        return changed

    def _get_sub_modules(self) -> set["ModuleReloader"]:
        site_package_paths = list(map(Path, site.getsitepackages()))
        sub_modules: set["ModuleReloader"] = set()
        for i in self.module.__dict__.values():
            # TODO: filter out buil-ins and other built-in modules
            # region check if the module file is one of project files.
            module_name: str | None = getattr(i, "__module__", None)
            if module_name is None:
                continue
            if module_name in excluded_sub_modules:
                continue
            module = sys.modules.get(module_name, None)
            if module is None:
                continue
            module_file: str | None = getattr(module, "__file__", None)
            if module_file is None:
                continue
            if not module_file.lower().endswith(".py"):
                continue
            module_path = Path(module_file)
            _continue: bool = False
            for spp in site_package_paths:
                if spp in module_path.parents:
                    _continue = True
                    break
            if _continue:
                continue
            # endregion
            sub_modules.add(ModuleReloader(module))

        return sub_modules

    @staticmethod
    def _lock_check() -> None:
        ModuleReloader._check_locked = True

    @staticmethod
    def _unlock_check() -> None:
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
