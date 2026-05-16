"""
thriftclass — automatic memory optimization for Python classes.

Usage:
    @thrift
    class MyClass:
        x: float
        y: float
        name: str
        active: bool
"""

from .core import thrift, ThriftConfig
from .report import MemoryReport

__all__ = ["thrift", "ThriftConfig", "MemoryReport"]
__version__ = "0.1.0"
