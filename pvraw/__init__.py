from .lib import BrukerLoader

__version__ = '1.1.1'

__all__ = ['BrukerLoader', '__version__']

def load(path):
    return BrukerLoader(path)
