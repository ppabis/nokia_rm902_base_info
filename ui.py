"""Colored terminal output; --no-color keeps every line plain."""
import colorama
from colorama import Fore, Style


class UI:
    def __init__(self, color=True):
        self.color = color
        colorama.init(strip=not color)

    def _paint(self, text, style):
        return f'{style}{text}{Style.RESET_ALL}' if self.color else text

    def banner(self):
        print(self._paint('Nokia Asha 501 (RM-902) — base information reader', Fore.CYAN + Style.BRIGHT))
        print(self._paint('Read-only: RAM loaders and named-object reads. No flash, erase or unlock.', Style.DIM))

    def header(self, text):
        print()
        print(self._paint(text, Fore.CYAN + Style.BRIGHT))

    def step(self, text):
        print()
        print(self._paint('[..] ' + text, Fore.BLUE + Style.BRIGHT))

    def ok(self, text):
        print(self._paint('[ok] ' + text, Fore.GREEN))

    def warn(self, text):
        print(self._paint('[!]  ' + text, Fore.YELLOW))

    def error(self, text):
        print(self._paint('[x]  ' + text, Fore.RED + Style.BRIGHT))

    def note(self, text):
        print(self._paint('     ' + text, Style.DIM))

    def field(self, name, value):
        print(f'  {self._paint(name.ljust(16), Style.BRIGHT)} {value}')
