"""PyQt6 compatibility shim.

桌面端有 PyQt6，核心引擎依赖 QObject / pyqtSignal / QThread 做异步通知。
但在无 GUI 的服务器环境（Web 后端）不安装 PyQt6，这个模块提供同 API 的
轻量替代，让核心引擎在两种环境下都能 import 并运行。

shim 语义：信号在「发射线程」内同步投递给所有已连接的槽（等价于 PyQt 的
DirectConnection）。这恰好是 Web 后端需要的——引擎在后台线程干活，然后
emit 一个信号，由等待方（Event）或回调处理。
"""
import threading

try:
    from PyQt6.QtCore import QObject, pyqtSignal, QThread  # noqa: F401
    QT_AVAILABLE = True
except ImportError:
    QT_AVAILABLE = False

    class _BoundSignal:
        """绑定到某个实例的信号。"""

        def __init__(self, name: str):
            self._name = name
            self._slots = []

        def connect(self, slot):
            if slot not in self._slots:
                self._slots.append(slot)

        def disconnect(self, slot=None):
            if slot is None:
                self._slots.clear()
            elif slot in self._slots:
                self._slots.remove(slot)

        def emit(self, *args):
            for slot in list(self._slots):
                slot(*args)

    class pyqtSignal:
        """类级信号描述符（镜像 PyQt6 的 pyqtSignal 用法）。"""

        def __init__(self, *types):
            self._types = types
            self._name = None

        def __set_name__(self, owner, name):
            self._name = name

        def __get__(self, instance, owner=None):
            if instance is None:
                return self
            attr = f"__sig_{self._name}"
            if not hasattr(instance, attr):
                setattr(instance, attr, _BoundSignal(self._name))
            return getattr(instance, attr)

    class QObject:
        """最小基类（无头环境不需要真 QObject）。"""

        def __init__(self, *args, **kwargs):
            pass

    class QThread:
        """在守护线程里跑 run()（PyQt6 QThread 的子集）。"""

        finished = pyqtSignal()

        def __init__(self, *args, **kwargs):
            self._thread = None

        def start(self):
            def _run():
                try:
                    self.run()
                finally:
                    self.finished.emit()
            self._thread = threading.Thread(target=_run, daemon=True)
            self._thread.start()

        def run(self):
            pass

        def deleteLater(self):
            # shim 无操作；对象由 GC 正常回收
            pass


__all__ = ["QObject", "pyqtSignal", "QThread", "QT_AVAILABLE"]
