from test import TestBox  # TODO: should be removed

from .window import Window

WINDOWS: list[Window] = [Window(TestBox, 100000, check_sub_modules=True, reload_sub_modules=True)]
