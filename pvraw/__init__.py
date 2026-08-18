from .lib import BrukerLoader

__version__ = '1.0.0'

__all__ = ['BrukerLoader', '__version__']

def load(path):
    return BrukerLoader(path)
