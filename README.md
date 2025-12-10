# PySide Widget Reloader

`pyside-widget-reloader` is a Python development utility that automatically reload PySide widgets whenever their module file is modified. This can be incredibly useful during the development of graphical user interfaces (GUIs) with PySide, as it eliminates the need for manual reloading of widgets or restarting the application when making changes to the widget files.

![reloader](https://github.com/user-attachments/assets/51ad66ae-7af3-4178-ad64-62f2d183a1d7)

## 🚀 Features

* **Hot reload PySide widgets** without restarting your application.
* **Recursive module watching** detect changes in a widget’s module and its submodules.

## 📦 Installation

```bash
pip install pyside-widget-reloader
```

## 🧩 Usage

### Basic Example

```python
from pwreloader import start_reloaders, ReloaderWindow
from myproject.widgets import MyWidget

start_reloaders(
  [ReloaderWindow(MyWidget, 1000)]
)
```

#### `start_reloaders()`

Starts all reloaders. Call this with a list of `ReloaderWindow`s.

#### `ReloaderWindow(WidgetClass, 1000)`

This manages reloading of your widget. Pass the widget *class* (not an instance) that you want to reload and interval *in milliseconds*.

## ⚙️ How It Works

The reloader isolates each widget in its own **child process**, each running its own `QApplication` instance. This ensures clean reloading without interfering with the main development environment.

### 🔄 File‑Change Detection

* At a user‑specified interval (in milliseconds), the system scans the **source file** of the widget’s module.
* It computes a **hash** of the source (optionally using a minified version to ignore changes that don't affect actual behavior, such as whitespace, comments, or variable name changes).
* If the hash changes, the module is marked for reload.
* Optionally, a **ruff check** can be performed; the reload proceeds only if the check passes.

### 🧭 Module Reload Logic

* The system can check only the current module, or **current module + submodules**, depending on settings.
* **check_sub_modules=True**: submodules are scanned for changes when scanning the main module, but only the main module is reloaded.
* **reload_sub_modules=True**: both changed submodules and the main module are reloaded.
* Parent modules of the widget's module also be reloaded.

### 🪄 Widget Reconstruction

Once the required modules are reloaded:

1. The old widget instance is removed from the window.
2. A **new instance** of the widget class is created.
3. The new widget is inserted into the window, replacing the previous one.

This provides a near‑instant feedback loop for UI development across isolated processes.

## 🛣️ Roadmap

### Compatibility

* Support latest Python versions.
* Support latest PySide versions.
* Add PyQt compatibility.
* Ensure dependencies (e.g., ruff, python‑minifier) are compatible across supported environments.
* Add automated CI (e.g., GitHub Actions) to test matrix of Python × PySide × PyQt.

### File & Module Scanning System

* Add ability to scan specific files for reload events.
* Allow users to include/exclude files or directories from scanning.
* Provide fine‑grained rules linking file changes to specific module reloads.
* Implement a mapping system: file → module(s) to reload.

## 🤝 Contributing

Contributions are welcome! Feel free to open issues, submit PRs, or discuss ideas.

## 📄 License

MIT License
