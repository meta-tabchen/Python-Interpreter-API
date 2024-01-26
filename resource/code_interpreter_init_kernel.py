import signal


import matplotlib.pyplot as plt

from matplotlib.font_manager import FontProperties
from sympy import Eq, solve, symbols  # noqa


def input(*args, **kwargs):  # noqa
    raise NotImplementedError("Python input() function is disabled.")


def _m6_timout_handler(_signum=None, _frame=None):
    raise TimeoutError("M6_CODE_INTERPRETER_TIMEOUT")


try:
    signal.signal(signal.SIGALRM, _m6_timout_handler)
except AttributeError:  # windows
    pass


class _M6CountdownTimer:
    @classmethod
    def start(cls, timeout: int):
        try:
            signal.alarm(timeout)
        except AttributeError:  # windows
            pass  # TODO: I haven't found a solution that works with jupyter yet.

    @classmethod
    def cancel(cls):
        try:
            signal.alarm(0)
        except AttributeError:  # windows
            pass  # TODO


_m6_font_prop = FontProperties(fname="{{M6_FONT_PATH}}")
plt.rcParams["font.family"] = _m6_font_prop.get_name()
